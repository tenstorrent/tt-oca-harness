# SPDX-License-Identifier: Apache-2.0
"""smu_jtag_reset_override_test - IC_RESET TDR override of EXT/SMC slices.

SMU IC_RESET TDR is 139 bits (68 SMC + 1 EXT ports + hold), not the 7-bit
standalone DTP smoke geometry.

Real checkers:
  - Default IC_RESET readback is all-ones
  - EXT enable=0/control=0 asserts ext ovrd=1 and ctrl_n=0
  - SMC cold_reset port override updates hierarchical SMC slice
  - Clearing TDR restores ovrd=0
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap
from cocotb.triggers import ClockCycles

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

# SMU SEP=0 IC_RESET geometry from smu.sv / jtag_ptap (real RTL).
_IC_NUM_PORTS = 69
_IC_LEN = 2 * _IC_NUM_PORTS + 1
_IC_DEFAULT = (1 << _IC_LEN) - 1
_IC_EXT = 0
_IC_SMC_FUSE = 1
_IC_SMC_WARM = 2
_IC_SMC_COOL = 3
_IC_SMC_COLD = 4
_IC_SMC_SS_COLD0 = 5
_IC_SMC_SS_WARM0 = 37



def _make_ptap(dut, period_ns: float, *, regs: tuple[str, ...] = ("DEBUG_CONTROL",)) -> OcahJtagTap:
    """Build OcahJtagTap against real TB JTAG pins (no Force / no fake DUT)."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=0x0000_0001,
        ir_width=6,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, 0x01)
    if "DEBUG_CONTROL" in regs:
        device.add_reg("DEBUG_CONTROL", 5, 0x18, write=True)
    if "IC_RESET" in regs:
        # SMU SEP=0: 69 ports * 2 + hold = 139
        device.add_reg("IC_RESET", 139, 0x0D, write=True)
    if "EXTEST" in regs:
        device.add_reg("EXTEST", 8, 0x04, write=True)
    jtag = OcahJtagTap(
        dut,
        name="smu_ptap",
        tck_period_ns=period_ns,
        ir_width=6,
        tap_type="ptap",
        signal_map={
            "tck": "jtag_tck",
            "tms": "jtag_tms",
            "tdi": "jtag_tdi",
            "tdo": "jtag_tdo",
            "trst": "jtag_trst",
            "tdo_oen": "jtag_tdo_oen",
        },
    )
    jtag.add_device(device)
    jtag.init_signals()
    return jtag


def _pack_ic_reset(
    *,
    reset_hold: int = 1,
    port_enable: dict[int, int] | None = None,
    port_control: dict[int, int] | None = None,
) -> int:
    value = _IC_DEFAULT & ~0x1
    value |= reset_hold & 0x1
    for idx, en in (port_enable or {}).items():
        bit = 1 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((en & 0x1) << bit)
    for idx, ctrl in (port_control or {}).items():
        bit = 2 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((ctrl & 0x1) << bit)
    return value & _IC_DEFAULT

@pyuvm.test()
class smu_jtag_reset_override_test(smu_base_test):
    """IC_RESET override/release on EXT and SMC cold-reset slices."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = _make_ptap(dut, self.cfg.jtag_period_ns, regs=("IC_RESET",))
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        default = await jtag.read("IC_RESET", shift_value=_IC_DEFAULT)
        sb.expect_eq(
            "IC_RESET default",
            int(default) & _IC_DEFAULT,
            _IC_DEFAULT,
        evidence="IC_RESET_DEFAULT")
        sb.expect_eq("ext ovrd idle", int(dut.jtag_ic_reset_ext_ovrd.value), 0, evidence="IC_RESET_DOMAIN_EXCL")
        sb.expect_eq("smc ovrd idle", int(dut.jtag_ic_reset_smc_ovrd.value), 0)

        ext_assert = _pack_ic_reset(
            reset_hold=1,
            port_enable={_IC_EXT: 0},
            port_control={_IC_EXT: 0},
        )
        await jtag.write("IC_RESET", ext_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("ext ovrd asserted", int(dut.jtag_ic_reset_ext_ovrd.value), 1)
        sb.expect_eq("ext ctrl_n asserted low", int(dut.jtag_ic_reset_ext_ctrl_n.value), 0)
        rb = await jtag.read("IC_RESET", shift_value=ext_assert)
        sb.expect_eq(
            "IC_RESET EXT pattern readback",
            int(rb) & _IC_DEFAULT,
            ext_assert,
        )

        smc_assert = _pack_ic_reset(
            reset_hold=1,
            port_enable={_IC_SMC_COLD: 0},
            port_control={_IC_SMC_COLD: 0},
        )
        await jtag.write("IC_RESET", smc_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("smc ovrd asserted", int(dut.jtag_ic_reset_smc_ovrd.value), 1)
        sb.expect_eq("smc ctrl_n asserted low", int(dut.jtag_ic_reset_smc_ctrl_n.value), 0)
        sb.expect_eq(
            "ext ovrd released while smc asserted",
            int(dut.jtag_ic_reset_ext_ovrd.value),
            0,
        )

        await jtag.write("IC_RESET", _IC_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq("ext ovrd cleared", int(dut.jtag_ic_reset_ext_ovrd.value), 0)
        sb.expect_eq("smc ovrd cleared", int(dut.jtag_ic_reset_smc_ovrd.value), 0)

        self.logger.info("smu_jtag_reset_override_test: IC_RESET EXT/SMC override checked")
