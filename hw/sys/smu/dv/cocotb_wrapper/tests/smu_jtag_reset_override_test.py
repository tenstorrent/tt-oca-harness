# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag_reset_override_test - IC_RESET TDR override of EXT/SMC slices.

SMU IC_RESET TDR is 155 bits on the SEP=1 wrapper (68 SMC + 8 SEP + 1 EXT ports
+ hold), not the 7-bit standalone DTP smoke geometry. The EXT port sits
nearest TDO, so it is the one port whose position does not survive a wrong
SEP slice width in the helper geometry: a DR shifted short of the TDR lands
the EXT fields in the SEP slice and the ext ovrd leg below fails.

The EXT override is applied and released in the order the DTP JTAG chapter
(hw/sys/dtp/doc/jtag.adoc) gives a hazard-free consumer: reset_control is
written in one Update-DR and reset_enable moved in a second, so the select
and the data input of the consumer's multiplexer never change together. The
override leaves the DTP with `.ovrd` active high and `.val` carrying
reset_control, so each staging update shows on the EXT slice alone.

Real checkers:
  - Default IC_RESET readback is all-ones over the whole DR
  - EXT control=0 staged with enable=1 drives ctrl_n=0 while ovrd stays 0
  - EXT enable=0/control=0 asserts ext ovrd=1 and ctrl_n=0
  - EXT control=1 staged with enable=0 drives ctrl_n=1 while ovrd stays 1
  - SMC cold_reset port override updates hierarchical SMC slice
  - Clearing TDR restores ovrd=0
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_jtag_helpers import (
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_EXT_PORT,
    SMU_IC_RESET_SMC_COLD_PORT,
    make_smu_jtag_tap,
    pack_ic_reset_ports,
    require_jtag_tdo_resolved,
)
from smu_base_test import smu_base_test


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_jtag_reset_override_test(smu_base_test):
    """IC_RESET override/release on EXT and SMC cold-reset slices."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        default = await jtag.read("IC_RESET", shift_value=SMU_IC_RESET_DEFAULT)
        require_jtag_tdo_resolved("IC_RESET default readback")
        sb.expect_eq(
            "IC_RESET default",
            int(default),
            SMU_IC_RESET_DEFAULT,
            evidence="IC_RESET_DEFAULT",
        )
        sb.expect_eq(
            "ext ovrd idle",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            0,
        )
        sb.expect_eq(
            "smc ovrd idle",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            0,
        )

        ext_staged = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_EXT_PORT: 1},
            port_control={SMU_IC_RESET_EXT_PORT: 0},
        )
        await jtag.write("IC_RESET", ext_staged)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext control staged low with the override still off (ovrd, ctrl_n)",
            (
                _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
                _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
            ),
            (0, 0),
            evidence="IC_RESET_EXT_STAGED",
        )

        ext_assert = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_EXT_PORT: 0},
            port_control={SMU_IC_RESET_EXT_PORT: 0},
        )
        await jtag.write("IC_RESET", ext_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext ovrd asserted",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            1,
        )
        sb.expect_eq(
            "ext ctrl_n asserted low",
            _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
            0,
        )
        sb.expect_eq(
            "smc idle while ext asserted",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            0,
            evidence="IC_RESET_DOMAIN_EXCL",
        )
        rb = await jtag.read("IC_RESET", shift_value=ext_assert)
        require_jtag_tdo_resolved("IC_RESET EXT pattern readback")
        sb.expect_eq(
            "IC_RESET EXT pattern readback",
            int(rb),
            ext_assert,
        )

        ext_release_staged = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_EXT_PORT: 0},
            port_control={SMU_IC_RESET_EXT_PORT: 1},
        )
        await jtag.write("IC_RESET", ext_release_staged)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext control staged high with the override still on (ovrd, ctrl_n)",
            (
                _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
                _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
            ),
            (1, 1),
            evidence="IC_RESET_EXT_RELEASE_STAGED",
        )

        smc_assert = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_SMC_COLD_PORT: 0},
            port_control={SMU_IC_RESET_SMC_COLD_PORT: 0},
        )
        await jtag.write("IC_RESET", smc_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "smc ovrd asserted",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            1,
        )
        sb.expect_eq(
            "smc ctrl_n asserted low",
            _sample(dut.jtag_ic_reset_smc_ctrl_n, "jtag_ic_reset_smc_ctrl_n"),
            0,
        )
        sb.expect_eq(
            "ext ovrd released while smc asserted",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            0,
            evidence="IC_RESET_DOMAIN_EXCL",
        )

        await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext ovrd cleared",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            0,
        )
        sb.expect_eq(
            "smc ovrd cleared",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            0,
        )

        self.logger.info("smu_jtag_reset_override_test: IC_RESET EXT/SMC override checked")
