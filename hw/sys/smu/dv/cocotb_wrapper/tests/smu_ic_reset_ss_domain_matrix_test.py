# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ic_reset_ss_domain_matrix_test - P4 IC_RESET SS cold/warm domains.

Exercises SS_COLD0 (port 12) and SS_WARM0 (port 44) on the wrapper, one at a
time, with mutual exclusion against fuse/warm/cool/cold and each other; the
indices are SMU_IC_RESET_SMC_SS_*_PORT in smu_jtag_helpers.

Does NOT close ss_reset_complete handshake (input tied dead on this bench).
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
    SMU_IC_RESET_SMC_SS_COLD0_PORT,
    SMU_IC_RESET_SMC_SS_WARM0_PORT,
    SMU_IC_RESET_SMC_WARM_PORT,
    make_smu_jtag_tap,
    pack_ic_reset_ports,
    read_smc_reset_ctrl_bit,
)
from smu_base_test import smu_base_test

# (port, ovrd leaf, val leaf, ss_idx or None for scalar)
_SS_DOMAINS = (
    (
        SMU_IC_RESET_SMC_SS_COLD0_PORT,
        "ss_cold_reset_n_ovrd",
        "ss_cold_reset_n_val",
        0,
        "IC_RESET_SS_COLD_OVRD",
    ),
    (
        SMU_IC_RESET_SMC_SS_WARM0_PORT,
        "ss_warm_reset_n_ovrd",
        "ss_warm_reset_n_val",
        0,
        "IC_RESET_SS_WARM_OVRD",
    ),
)

_SCALAR_OVRDS = (
    (SMU_IC_RESET_SMC_FUSE_PORT, "fuse_reset_n_ovrd", None),
    (SMU_IC_RESET_SMC_WARM_PORT, "warm_reset_n_ovrd", None),
    (SMU_IC_RESET_SMC_COOL_PORT, "cool_reset_n_ovrd", None),
    (SMU_IC_RESET_SMC_COLD_PORT, "cold_reset_n_ovrd", None),
)


@pyuvm.test()
class smu_ic_reset_ss_domain_matrix_test(smu_base_test):
    """IC_RESET SS cold0/warm0 with mutual exclusion."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        for _, ovrd_name, _, idx, _ in _SS_DOMAINS:
            sb.expect_eq(
                f"idle {ovrd_name}[{idx}]",
                read_smc_reset_ctrl_bit(dut, ovrd_name, idx),
                0,
            )

        for port, ovrd_name, val_name, idx, token in _SS_DOMAINS:
            pattern = pack_ic_reset_ports(
                reset_hold=1,
                port_enable={port: 0},
                port_control={port: 0},
            )
            await jtag.write("IC_RESET", pattern)
            await ClockCycles(dut.clk_smu_i, 16)

            sb.expect_eq(
                f"{token} asserted",
                read_smc_reset_ctrl_bit(dut, ovrd_name, idx),
                1,
                evidence=token,
            )
            sb.expect_eq(
                f"{val_name}[{idx}] asserted low",
                read_smc_reset_ctrl_bit(dut, val_name, idx),
                0,
                evidence=token,
            )

            # Mutual exclusion vs scalar SMC domains.
            for _, other_ovrd, _ in _SCALAR_OVRDS:
                sb.expect_eq(
                    f"IC_RESET_SS_EXCL: {other_ovrd} idle while {token}",
                    read_smc_reset_ctrl_bit(dut, other_ovrd),
                    0,
                    evidence="IC_RESET_SS_EXCL",
                )

            # Mutual exclusion vs the other SS domain.
            for other_port, other_ovrd, _, other_idx, other_tok in _SS_DOMAINS:
                if other_port == port:
                    continue
                sb.expect_eq(
                    f"IC_RESET_SS_EXCL: {other_tok} idle while {token}",
                    read_smc_reset_ctrl_bit(dut, other_ovrd, other_idx),
                    0,
                    evidence="IC_RESET_SS_EXCL",
                )

            await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                f"{token} released",
                read_smc_reset_ctrl_bit(dut, ovrd_name, idx),
                0,
            )

        self.logger.info("smu_ic_reset_ss_domain_matrix_test: SS cold/warm OK")
