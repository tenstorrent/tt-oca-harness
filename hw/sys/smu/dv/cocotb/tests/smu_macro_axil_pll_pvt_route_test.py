# SPDX-License-Identifier: Apache-2.0
"""smu_macro_axil_pll_pvt_route_test - P4 PLL/PVT/extension AXI-Lite routing.

Issues JTAG2AXI reads to macro windows and proves:
  1. matching tb_axil_*_active pulses
  2. other macro ports stay idle (isolation)
  3. DECERR + 0xBADCAB1E from boundary err_slv

Does NOT defend macro-internal PLL/PVT function (err_slv terminators only).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_DECERR,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

BLOCK_DATA = 0xBADC_AB1E

_ROUTABLE = [
    ("PLL", "tb_axil_pll_active", 0xC000_3000),
    ("PVT", "tb_axil_pvt_active", 0xC000_7000),
    ("EXTENSION", "tb_axil_extension_active", 0xC040_0000),
]
_ALL_ACTIVE = [m[1] for m in _ROUTABLE]


class _AxilActiveMonitor:
    def __init__(self, dut) -> None:
        self.dut = dut
        self.sigs = {name: getattr(dut, name) for name in _ALL_ACTIVE}
        self.latched = {name: 0 for name in _ALL_ACTIVE}
        self._run = True

    def reset(self) -> None:
        self.latched = {name: 0 for name in _ALL_ACTIVE}

    async def run(self) -> None:
        while self._run:
            await RisingEdge(self.dut.clk_smu_i)
            for name, sig in self.sigs.items():
                v = sig.value
                if v.is_resolvable and int(v):
                    self.latched[name] = 1


@pyuvm.test()
class smu_macro_axil_pll_pvt_route_test(smu_base_test):
    """Macro windows route to own port with DECERR poison + isolation."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()

        mon = _AxilActiveMonitor(dut)
        cocotb.start_soon(mon.run())

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            await ClockCycles(dut.clk_smu_i, 8)
            for name in _ALL_ACTIVE:
                sb.expect_eq(f"{name} idle baseline", int(getattr(dut, name).value), 0)

            for macro_name, active_attr, addr in _ROUTABLE:
                await ClockCycles(dut.clk_smu_i, 8)
                mon.reset()
                st, rdata = await jtag2axi_single_read(jtag, addr)
                await ClockCycles(dut.clk_smu_i, 4)

                token = {
                    "PLL": "PLL_AXIL_ACTIVE",
                    "PVT": "PVT_AXIL_ACTIVE",
                    "EXTENSION": "EXTENSION_AXIL_ACTIVE",
                }[macro_name]
                sb.expect_eq(
                    f"{token} pulsed for {macro_name}",
                    mon.latched[active_attr],
                    1,
                    evidence=token,
                )
                for other in _ALL_ACTIVE:
                    if other == active_attr:
                        continue
                    sb.expect_eq(
                        f"MACRO_ISOLATION: {other} idle during {macro_name}",
                        mon.latched[other],
                        0,
                        evidence="MACRO_ISOLATION",
                    )
                sb.expect_eq(
                    f"{macro_name} DECERR status",
                    st,
                    J2A_STATUS_DECERR,
                    evidence="MACRO_DECERR_POISON",
                )
                sb.expect_eq(
                    f"MACRO_DECERR_POISON {macro_name}",
                    int(rdata) & 0xFFFF_FFFF,
                    BLOCK_DATA,
                    evidence="MACRO_DECERR_POISON",
                )
                self.logger.info(
                    "macro route OK: %s @0x%08x active=%s DECERR poison",
                    macro_name,
                    addr,
                    active_attr,
                )
        finally:
            mon._run = False
            release_forced(forced)

        self.logger.info("smu_macro_axil_pll_pvt_route_test: 3 macros OK")
