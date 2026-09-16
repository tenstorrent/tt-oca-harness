# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CORE0 WDT first timeout sets WDOGIP0 and holds it, via J2A. SEP=1, no Force.

"Sticky" is measured, not assumed: WDOGIP0 is clear before the enable, set
once the counter has passed CMP, and then sampled STICKY_SAMPLES more times
across STICKY_GAP_CYCLES each with no software clear in between; every sample
must still show it set. IRQ/PLIC delivery is not claimed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, wdt_bm
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
    wdt_unlock,
)

WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_COUNT = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_COUNT_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
WDT_IP0_MASK = wdt_bm("WDT__CTRL__WDOGIP0_bm")
WDT_ALWAYS_MASK = wdt_bm("WDT__CTRL__WDOGENALWAYS_bm")
WDT_ZEROCMP_MASK = wdt_bm("WDT__CTRL__WDOGZEROCMP_bm")
WDT_CTRL_EN = WDT_ALWAYS_MASK | WDT_ZEROCMP_MASK
CMP_SMALL = 0x10
CMP_MASK = wdt_bm("WDT__CMP__WDOGCMP0_bm")
STICKY_SAMPLES = 4
STICKY_GAP_CYCLES = 512


class smu_smc_wdt_timeout_irq_test_seq:
    """CORE0 WDT first timeout sets WDOGIP0, which then holds with no software clear."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, jtag, addr: int) -> tuple[int, int]:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"WDT RD @0x{addr:08x}")
        return st, int(rdata) & 0xFFFF_FFFF

    async def _wr32(self, jtag, addr: int, data: int) -> int:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"WDT WR @0x{addr:08x}")
        return st

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self.s1_ok = True
        sb.expect_eq("CHK-WDT-TO-GATE-OPEN", gate, 0)

        st_u = await wdt_unlock(jtag)
        if st_u != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={st_u}")
        st_c = await self._wr32(jtag, WDT_CMP, CMP_SMALL)
        if st_c != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CMP program status={st_c}")
        st_rb, cmp_rb = await self._rd32(jtag, WDT_CMP)
        if st_rb != J2A_STATUS_SUCCESS or (cmp_rb & CMP_MASK) != CMP_SMALL:
            raise AssertionError(f"WDT_CMP rb st={st_rb} data=0x{cmp_rb:x} want 0x{CMP_SMALL:x}")
        sb.expect_eq("CHK-WDT-TO-CMP", cmp_rb & CMP_MASK, CMP_SMALL)

        st_pre, ctrl_pre = await self._rd32(jtag, WDT_CTRL)
        if st_pre != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CTRL pre-enable status={st_pre}")
        if ctrl_pre & WDT_IP0_MASK:
            raise AssertionError(f"WDOGIP0 already set before enable CTRL=0x{ctrl_pre:08x}")
        sb.expect_eq("CHK-WDT-TO-IP0-PRE", ctrl_pre & WDT_IP0_MASK, 0)

        st_u2 = await wdt_unlock(jtag)
        if st_u2 != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock before CTRL status={st_u2}")
        st_e = await self._wr32(jtag, WDT_CTRL, WDT_CTRL_EN)
        if st_e != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CTRL enable status={st_e}")
        st_cr, ctrl0 = await self._rd32(jtag, WDT_CTRL)
        if st_cr != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CTRL readback status={st_cr}")
        if not (ctrl0 & WDT_ALWAYS_MASK) or not (ctrl0 & WDT_ZEROCMP_MASK):
            raise AssertionError(f"WDT_CTRL enable bits missing: 0x{ctrl0:08x}")
        self.s2_ok = True
        sb.expect_eq(
            "CHK-WDT-TO-EN",
            bool(ctrl0 & WDT_ALWAYS_MASK) and bool(ctrl0 & WDT_ZEROCMP_MASK),
            True,
        )

        await ClockCycles(dut.clk_smu_i, max(CMP_SMALL * 64, 2048))
        ip0 = False
        last_ctrl = 0
        for _ in range(32):
            st_f, ctrl_f = await self._rd32(jtag, WDT_CTRL)
            last_ctrl = ctrl_f
            if st_f == J2A_STATUS_SUCCESS and (last_ctrl & WDT_IP0_MASK):
                ip0 = True
                break
            await ClockCycles(dut.clk_smu_i, 512)
        if not ip0:
            raise AssertionError(f"WDOGIP0 never set (CTRL=0x{last_ctrl:08x})")
        # Hold window: nothing clears IP0 here, so a WDT whose pending bit
        # followed the counter (which keeps wrapping under WDOGZEROCMP) would
        # drop it inside this window.
        held = []
        for i in range(STICKY_SAMPLES):
            await ClockCycles(dut.clk_smu_i, STICKY_GAP_CYCLES)
            st_h, ctrl_h = await self._rd32(jtag, WDT_CTRL)
            if st_h != J2A_STATUS_SUCCESS:
                raise AssertionError(f"WDT_CTRL hold sample {i} status={st_h}")
            held.append(bool(ctrl_h & WDT_IP0_MASK))
            if not held[-1]:
                raise AssertionError(
                    f"WDOGIP0 dropped at hold sample {i} (CTRL=0x{ctrl_h:08x}); it is not sticky"
                )
        st_n, _ = await self._rd32(jtag, WDT_COUNT)
        if st_n != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_COUNT after IP0 status={st_n}")
        self.s3_ok = True
        self._log(
            f"WDT_WDOGIP0 CTRL=0x{last_ctrl:08x} held over {STICKY_SAMPLES} samples "
            f"{STICKY_GAP_CYCLES} cycles apart; COUNT readable"
        )
        sb.expect_eq(
            "CHK-WDT-IP0 set after enable+CMP and held across the window",
            (ip0, *held),
            (True,) + (True,) * STICKY_SAMPLES,
            evidence="WDT_WDOGIP0",
        )
