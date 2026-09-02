# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""WDT / AON-timer CSR driver.

Direct-AXI access to the SEP WDT aon_timer block (base 0x1080_1000) over the
CPU-LSU master (no_cpu). Exercises the aon_timer internals beyond the bark/bite/NMI
story: the WKUP (wakeup) timer + its wkup_expired RW1C status, the WDOG
counter/pet, and the WDOG_REGWEN config-lock.

Register map (vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/aon_timer.rdl; offsets verified):
  WKUP_CTRL   +0x04  enable[0], prescaler[12:1]
  WKUP_THOLD  +0x08 (hi) / +0x0C (lo)   64-bit threshold
  WKUP_COUNT  +0x10 (hi) / +0x14 (lo)   64-bit counter (RW by sw + hw)
  WDOG_REGWEN +0x18  regwen[0] (reset 1; writing 0 locks WDOG_CTRL/BARK/BITE)
  WDOG_CTRL   +0x1C  enable[0]
  WDOG_BARK_THOLD +0x20 / WDOG_BITE_THOLD +0x24 / WDOG_COUNT +0x28
  INTR_STATE  +0x2C  wkup_expired[0] RW1C, wdog_bark[1] RW1C
  INTR_TEST   +0x30  wkup_expired[0] / wdog_bark[1] force (prim_intr_hw)
  WKUP_CAUSE  +0x34  wakeup-request; level-held, AON-domain, cleared by WRITING 0
                     once the count>=thold condition is gone
WDOG_REGWEN gates WDOG_CTRL / WDOG_BARK_THOLD / WDOG_BITE_THOLD only
(aon_timer_reg_top.sv src_regwen_i): the WKUP registers and WDOG_COUNT stay
writable while the watchdog config is locked.
The WDT runs on clk_wdt (~1000x slower than the core clock in this env); the block
is always clocked (no CLOCK_GATE_CTRL ungate needed).
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

WDT_BASE = sym("WDT_TIMER_REG_MAP_BASE_ADDR")
WKUP_CTRL = WDT_BASE + 0x04
WKUP_THOLD_HI = WDT_BASE + 0x08
WKUP_THOLD_LO = WDT_BASE + 0x0C
WKUP_COUNT_HI = WDT_BASE + 0x10
WKUP_COUNT_LO = WDT_BASE + 0x14
WDOG_REGWEN = WDT_BASE + 0x18
WDOG_CTRL = WDT_BASE + 0x1C
WDOG_BARK_THOLD = WDT_BASE + 0x20
WDOG_BITE_THOLD = WDT_BASE + 0x24
WDOG_COUNT = WDT_BASE + 0x28
INTR_STATE = WDT_BASE + 0x2C
INTR_TEST = WDT_BASE + 0x30
WKUP_CAUSE = WDT_BASE + 0x34

WKUP_ENABLE = 1 << 0
WKUP_PRESCALER_SHIFT = 1  # WKUP_CTRL.prescaler[12:1]
WKUP_PRESCALER_MAX = 0xFFF
WDOG_ENABLE = 1 << 0
INTR_TEST_WKUP_EXPIRED = 1 << 0
INTR_WKUP_EXPIRED = 1 << 0
INTR_WDOG_BARK = 1 << 1

RESP_OKAY = 0


class SepWdtCfg:
    """Seeded thresholds for the WDT/AON-timer sweep.

    Single source of truth for the test's programmable thresholds: the small WKUP
    threshold that must expire within the poll budget, the large WKUP threshold that
    must NOT expire during the counter-advance window, and the WDOG_BARK_THOLD value
    written before the REGWEN lock (plus a distinct post-lock attempt value), the
    WKUP_CTRL prescaler divisor, and the values written to the registers the WDOG
    lock must not reach. The count/expiry/prescale/pet/lock contract is identical
    for every threshold; the randomization just varies the values per seed. Seed
    logged. Single seed per invocation.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.wkup_thold = rng.randrange(4, 33)  # small: expires in <=32 ticks
        self.wkup_high_thold = rng.randrange(
            0x4_0000, 0x10_0001
        )  # large: no expiry in the count window
        # Floored at 2, not 1, so that bark_prelock // 2 below is both non-zero
        # and STRICTLY less than the threshold. At a drawn value of 1 the probe
        # would equal the bark threshold and trip it.
        self.bark_prelock = rng.randrange(2, 0x1_0000)  # nonzero pre-lock BARK_THOLD
        self.bark_postlock = self.bark_prelock ^ 0xFFFF  # distinct locked-write attempt
        # WKUP_CTRL.prescaler: the wakeup counter advances once every
        # (prescaler + 1) clk_wdt ticks (aon_timer_core.sv wkup_incr), so a value
        # well above 1 makes the divided rate distinguishable from prescaler=0
        # inside one measurement window.
        self.wkup_prescaler = rng.randrange(24, 64)
        # Post-lock WKUP_THOLD_LO probe value: a register the WDOG lock must NOT
        # reach. Distinct from every threshold above so the readback is attributable.
        self.postlock_wkup_thold = 0x1000_0000 | rng.randrange(1, 0x1_0000)
        # Post-lock WDOG_COUNT probe value. It must sit STRICTLY below
        # bark_prelock: the watchdog is still enabled and REGWEN-locked when this
        # value is written, so a probe at or above the bark threshold fires an
        # unintended bark. With bark_prelock floored at 2, half of it is always
        # non-zero and always strictly below, so the "the write landed" compare
        # stays meaningful without disturbing the watchdog.
        self.postlock_wdog_count = self.bark_prelock // 2
        assert 0 < self.postlock_wdog_count < self.bark_prelock

    def summary(self) -> str:
        return (
            f"seed={self.seed} wkup_thold={self.wkup_thold} "
            f"wkup_high_thold=0x{self.wkup_high_thold:x} "
            f"bark_prelock=0x{self.bark_prelock:04x} bark_postlock=0x{self.bark_postlock:04x} "
            f"wkup_prescaler={self.wkup_prescaler} "
            f"postlock_wkup_thold=0x{self.postlock_wkup_thold:08x}"
        )


class SepWdtAon(SepAxiRegDriver):
    """Direct-AXI R/W to the WDT aon_timer block (32-bit beats)."""

    _DRIVER_TAG = "WDT"

    async def write(self, addr: int, data: int) -> None:
        await self._wr(addr, data)

    async def read(self, addr: int) -> int:
        return await self._rd(addr)

    async def write_tolerant(self, addr: int, data: int) -> int:
        """Write tolerating a non-OKAY response (a REGWEN-locked register may reject
        the write); return the AXI resp_code. The proof is the read-back value."""
        seq = SepAxiAccessSeq(
            "wdt_wr_tol",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            size=self._AXI_SIZE,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code
