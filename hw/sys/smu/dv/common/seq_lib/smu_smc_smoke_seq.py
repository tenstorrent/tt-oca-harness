# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC firmware boot sequence for the production SMU wrapper (SEP=1 elaboration)."""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge


class SmuSmcSmokeSeq:
    """Observe architectural SMC firmware completion with bounded progress logs."""

    def __init__(self, test, scoreboard) -> None:
        self.test = test
        self.sb = scoreboard
        self.dut = cocotb.top
        self.log = test.logger

    async def run(self) -> None:
        # Firmware boot is inherently a single reset-to-completion transaction.
        # Reset timing is randomized by smu_base_test; all evidence comes from
        # independent DUT activity and architectural pass/fail signals.
        max_cycles = int(os.environ.get("SMU_SMC_BOOT_MAX_CYCLES", "2000000"), 0)
        heartbeat = max(1, max_cycles // 20)
        self.log.info("=" * 70)
        self.log.info("DUT_TAG=WRAPPER TEST: SMC firmware boot under production smu_wrapper SEP=1")
        self.log.info("=" * 70)
        self.log.info(
            "Bring-up evidence: smc_fuse_sense_done=%d smc_fuse_reset_n_delayed=%d "
            "rst_primary=%d smc_init_mem_done=%d rst_cold_n=%d powergood=%d",
            self.test.read_int(self.dut.smc_fuse_sense_done_o, "smc_fuse_sense_done_o"),
            self.test.read_int(self.dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"),
            self.test.read_int(self.dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"),
            self.test.read_int(self.dut.smc_init_mem_done_o, "smc_init_mem_done_o"),
            self.test.read_int(self.dut.rst_cold_n_o, "rst_cold_n_o"),
            self.test.read_int(self.dut.powergood_o, "powergood_o"),
        )

        # The wrapper elaborates SEP=1, so the real SEP reset tree is present and
        # cold reset must hold the SEP in reset (the same check the SEP=1 leg of
        # smu_wrapper_elaboration_seq makes). SEP fuse-done after release is a
        # SEP-side observation this SMC boot claim does not own.
        assert self.test.pre_release_sep_reset == 0, (
            "SEP=1 wrapper must assert SEP reset during cold reset: "
            f"expected=0 observed={self.test.pre_release_sep_reset}"
        )
        self.log.info(
            "Post-release SEP fuse-done observed=%d (SEP=1 wrapper, +skip_fuse_sense)",
            self.test.post_release_sep_fuse,
        )

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            passed = self.test.read_int(self.dut.smc_test_pass_o, "smc_test_pass_o")
            failed = self.test.read_int(self.dut.smc_test_fail_o, "smc_test_fail_o")
            rom_reads = self.test.read_int(self.dut.smc_rom_read_count_o, "smc_rom_read_count_o")
            scratch_writes = self.test.read_int(
                self.dut.smc_scratch_write_count_o,
                "smc_scratch_write_count_o",
            )
            self.sb.sample(
                passed=passed,
                failed=failed,
                rom_reads=rom_reads,
                scratch_writes=scratch_writes,
            )
            if failed:
                raise AssertionError(
                    f"SMC firmware FAIL at cycle={cycle} rom_reads={rom_reads} "
                    f"scratch_writes={scratch_writes}"
                )
            if passed:
                # smc_test_pass_o is combinational on the scratch register while
                # the TB write counter updates on the following clock edge, so
                # settle before taking the final evidence sample.
                for _ in range(2):
                    await RisingEdge(self.dut.clk_smu_i)
                rom_reads = self.test.read_int(
                    self.dut.smc_rom_read_count_o, "smc_rom_read_count_o"
                )
                scratch_writes = self.test.read_int(
                    self.dut.smc_scratch_write_count_o,
                    "smc_scratch_write_count_o",
                )
                self.sb.sample(
                    passed=passed,
                    failed=failed,
                    rom_reads=rom_reads,
                    scratch_writes=scratch_writes,
                )
                self.log.info(
                    "SMC PASS cycle=%d rom_reads=%d scratch_writes=%d",
                    cycle,
                    rom_reads,
                    scratch_writes,
                )
                return
            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "SMC boot heartbeat cycle=%d rom_reads=%d scratch_writes=%d",
                    cycle,
                    rom_reads,
                    scratch_writes,
                )
        raise AssertionError(
            f"SMC boot timeout after {max_cycles} cycles: "
            f"rom_reads={self.sb.max_rom_reads} "
            f"scratch_writes={self.sb.max_scratch_writes}"
        )
