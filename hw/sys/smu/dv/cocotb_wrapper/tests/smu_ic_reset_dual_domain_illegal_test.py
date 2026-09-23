# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ic_reset_dual_domain_illegal_test - dual IC_RESET in one DR.

smu_ic_reset_smc_multi_domain_test proves one-domain-at-a-time mutual
exclusion. This corner packs two
SMC ports in a single IC_RESET update (IEEE §17 allows independent ports)
and checks:

  1. Both intended ovrd bits assert; vals driven low
  2. Non-selected domains stay idle (no bleed)
  3. DEFAULT write clears both (no sticky dual ovrd)

Pairs: fuse+warm, cool+cold. Must FAIL if only one of a pair asserts, a third
domain asserts, or ovrd sticks after DEFAULT.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_jtag_helpers import (
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_SMC_COLD_PORT,
    SMU_IC_RESET_SMC_COOL_PORT,
    SMU_IC_RESET_SMC_FUSE_PORT,
    SMU_IC_RESET_SMC_WARM_PORT,
    make_smu_jtag_tap,
    pack_ic_reset_ports,
    read_smc_reset_ctrl_bit,
)
from smu_base_test import smu_base_test

_ALL = (
    (SMU_IC_RESET_SMC_FUSE_PORT, "fuse_reset_n_ovrd", "fuse_reset_n_val"),
    (SMU_IC_RESET_SMC_WARM_PORT, "warm_reset_n_ovrd", "warm_reset_n_val"),
    (SMU_IC_RESET_SMC_COOL_PORT, "cool_reset_n_ovrd", "cool_reset_n_val"),
    (SMU_IC_RESET_SMC_COLD_PORT, "cold_reset_n_ovrd", "cold_reset_n_val"),
)

# (label, ports to assert together)
_PAIRS = (
    (
        "fuse+warm",
        (SMU_IC_RESET_SMC_FUSE_PORT, SMU_IC_RESET_SMC_WARM_PORT),
    ),
    (
        "cool+cold",
        (SMU_IC_RESET_SMC_COOL_PORT, SMU_IC_RESET_SMC_COLD_PORT),
    ),
)


@pyuvm.test()
class smu_ic_reset_dual_domain_illegal_test(smu_base_test):
    """Dual SMC IC_RESET ports in one DR: both assert, others idle, release clean."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        for _, ovrd_name, _ in _ALL:
            sb.expect_eq(
                f"idle {ovrd_name}",
                read_smc_reset_ctrl_bit(dut, ovrd_name),
                0,
            )

        for label, ports in _PAIRS:
            enable = {p: 0 for p in ports}
            control = {p: 0 for p in ports}
            pattern = pack_ic_reset_ports(
                reset_hold=1,
                port_enable=enable,
                port_control=control,
            )
            await jtag.write("IC_RESET", pattern)
            await ClockCycles(dut.clk_smu_i, 16)

            selected = set(ports)
            for port, ovrd_name, val_name in _ALL:
                if port in selected:
                    sb.expect_eq(
                        f"{label} {ovrd_name} asserted",
                        read_smc_reset_ctrl_bit(dut, ovrd_name),
                        1,
                    )
                    sb.expect_eq(
                        f"{label} {val_name} low",
                        read_smc_reset_ctrl_bit(dut, val_name),
                        0,
                    )
                else:
                    sb.expect_eq(
                        f"{label} {ovrd_name} idle (no bleed)",
                        read_smc_reset_ctrl_bit(dut, ovrd_name),
                        0,
                    )

            await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
            await ClockCycles(dut.clk_smu_i, 16)
            for port, ovrd_name, _ in _ALL:
                if port not in selected:
                    continue
                sb.expect_eq(
                    f"{label} {ovrd_name} cleared after DEFAULT",
                    read_smc_reset_ctrl_bit(dut, ovrd_name),
                    0,
                    evidence="IC_RESET_DUAL_PACK",
                )

        self.logger.info("smu_ic_reset_dual_domain_illegal_test: dual pairs OK (no bleed/sticky)")
