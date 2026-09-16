# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ic_reset_smc_multi_domain_test - IC_RESET SMC multi-domain.

Exercises SMC fuse/warm/cool/cold IC_RESET ports one at a time and checks
hierarchical jtag_smc_reset_ctrl ovrd/val fields for mutual exclusion.

Port map on the wrapper: EXT@0, the seven SEP ports, then SMC fuse@8, warm@9,
cool@10, cold@11 (SMU_IC_RESET_SMC_*_PORT in smu_jtag_helpers).

Must FAIL if wrong port toggles wrong reset domain.
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


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


# (port, ovrd leaf, val leaf) under u_dut.jtag_smc_reset_ctrl
_DOMAINS = (
    (SMU_IC_RESET_SMC_FUSE_PORT, "fuse_reset_n_ovrd", "fuse_reset_n_val"),
    (SMU_IC_RESET_SMC_WARM_PORT, "warm_reset_n_ovrd", "warm_reset_n_val"),
    (SMU_IC_RESET_SMC_COOL_PORT, "cool_reset_n_ovrd", "cool_reset_n_val"),
    (SMU_IC_RESET_SMC_COLD_PORT, "cold_reset_n_ovrd", "cold_reset_n_val"),
)


@pyuvm.test()
class smu_ic_reset_smc_multi_domain_test(smu_base_test):
    """IC_RESET one-domain-at-a-time with mutual exclusion."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        # Idle: all SMC ovrd bits clear.
        for _, ovrd_name, _ in _DOMAINS:
            sb.expect_eq(
                f"idle {ovrd_name}",
                read_smc_reset_ctrl_bit(dut, ovrd_name),
                0,
            )

        for port, ovrd_name, val_name in _DOMAINS:
            pattern = pack_ic_reset_ports(
                reset_hold=1,
                port_enable={port: 0},
                port_control={port: 0},
            )
            await jtag.write("IC_RESET", pattern)
            await ClockCycles(dut.clk_smu_i, 16)

            sb.expect_eq(
                f"{ovrd_name} asserted",
                read_smc_reset_ctrl_bit(dut, ovrd_name),
                1,
            )
            sb.expect_eq(
                f"{val_name} asserted low",
                read_smc_reset_ctrl_bit(dut, val_name),
                0,
            )

            # Mutual exclusion: other domains idle.
            for other_port, other_ovrd, _ in _DOMAINS:
                if other_port == port:
                    continue
                sb.expect_eq(
                    f"{other_ovrd} idle while {ovrd_name}",
                    read_smc_reset_ctrl_bit(dut, other_ovrd),
                    0,
                    evidence="IC_RESET_DOMAIN_EXCL",
                )

            # TB cold mirror only tracks cold domain.
            if port == SMU_IC_RESET_SMC_COLD_PORT:
                sb.expect_eq(
                    "TB smc cold ovrd",
                    _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
                    1,
                )
                sb.expect_eq(
                    "TB smc cold ctrl_n",
                    _sample(dut.jtag_ic_reset_smc_ctrl_n, "jtag_ic_reset_smc_ctrl_n"),
                    0,
                )

            await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                f"{ovrd_name} released",
                read_smc_reset_ctrl_bit(dut, ovrd_name),
                0,
            )

        self.logger.info("smu_ic_reset_smc_multi_domain_test: 4 domains OK")
