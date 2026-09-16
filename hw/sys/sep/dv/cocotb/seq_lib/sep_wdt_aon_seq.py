# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""WDT / AON-timer CSR driver.

Direct-AXI access to the SEP WDT aon_timer block (base 0x1080_1000) over the
CPU-LSU master (no_cpu). Exercises the aon_timer internals beyond the bark/bite/NMI
story: the WKUP (wakeup) timer + its wkup_expired RW1C status, the WDOG
counter/pet, and the WDOG_REGWEN config-lock.

Register map (vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/aon_timer.rdl):
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
(aon_timer.hjson regwen linkage, checked at the CHK-REGWEN-SCOPE site): the
WKUP registers and WDOG_COUNT stay writable while the watchdog config is
locked.
The WDT runs on clk_wdt (~1000x slower than the core clock in this env); the block
is always clocked (no CLOCK_GATE_CTRL ungate needed).
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import WDT_TIMER, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

WDT_BASE = sym("WDT_TIMER_REG_MAP_BASE_ADDR")
WKUP_CTRL = WDT_TIMER.addr("WKUP_CTRL")
WKUP_THOLD_HI = WDT_TIMER.addr("WKUP_THOLD_HI")
WKUP_THOLD_LO = WDT_TIMER.addr("WKUP_THOLD_LO")
WKUP_COUNT_HI = WDT_TIMER.addr("WKUP_COUNT_HI")
WKUP_COUNT_LO = WDT_TIMER.addr("WKUP_COUNT_LO")
WDOG_REGWEN = WDT_TIMER.addr("WDOG_REGWEN")
WDOG_CTRL = WDT_TIMER.addr("WDOG_CTRL")
WDOG_BARK_THOLD = WDT_TIMER.addr("WDOG_BARK_THOLD")
WDOG_BITE_THOLD = WDT_TIMER.addr("WDOG_BITE_THOLD")
WDOG_COUNT = WDT_TIMER.addr("WDOG_COUNT")
INTR_STATE = WDT_TIMER.addr("INTR_STATE")
INTR_TEST = WDT_TIMER.addr("INTR_TEST")
WKUP_CAUSE = WDT_TIMER.addr("WKUP_CAUSE")

WKUP_ENABLE = WDT_TIMER.field_mask("WKUP_CTRL", "enable")
WKUP_PRESCALER_SHIFT = WDT_TIMER.field_lsb("WKUP_CTRL", "prescaler")
WDOG_ENABLE = WDT_TIMER.field_mask("WDOG_CTRL", "enable")
INTR_TEST_WKUP_EXPIRED = WDT_TIMER.field_mask("INTR_TEST", "wkup_timer_expired")
INTR_WKUP_EXPIRED = WDT_TIMER.field_mask("INTR_STATE", "wkup_timer_expired")
INTR_WDOG_BARK = WDT_TIMER.field_mask("INTR_STATE", "wdog_timer_bark")

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
        # Floored well above the REGWEN-scope check's counter run floor. That check
        # lets the enabled watchdog climb past a literal floor of a few tens of
        # ticks before it probes WDOG_COUNT, and by then THIS value is the live
        # bark threshold: the pre-lock leg overwrites the high park value from the
        # pet check and REGWEN locks it there. A draw below the run floor would
        # bark inside the probe.
        self.bark_prelock = rng.randrange(0x1000, 0x1_0000)  # pre-lock BARK_THOLD
        self.bark_postlock = self.bark_prelock ^ 0xFFFF  # distinct locked-write attempt
        # WKUP_CTRL.prescaler: the wakeup counter advances once every
        # (prescaler + 1) ticks -- the OpenTitan AON Timer specification's
        # cycles-per-tick rule, carried by sep_spec_tables -- so a value well above
        # 1 makes the divided rate distinguishable from prescaler=0 inside one
        # measurement window.
        self.wkup_prescaler = rng.randrange(24, 64)
        # Post-lock WKUP_THOLD_LO probe value: a register the WDOG lock must NOT
        # reach. Distinct from every threshold above so the readback is attributable.
        self.postlock_wkup_thold = 0x1000_0000 | rng.randrange(1, 0x1_0000)

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
