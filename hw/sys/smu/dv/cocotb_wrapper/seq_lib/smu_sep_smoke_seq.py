# SPDX-License-Identifier: Apache-2.0
"""Real-SEP firmware boot-readiness sequence inside the OSS SMU wrapper."""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge


class SmuSepSmokeSeq:
    """Collect reset, trace, and TCM evidence until SEP boot readiness.

    The sequence finishes as soon as the scoreboard has every required
    boot-readiness evidence item (boot-ROM fetch, ICCM execution, DCCM
    stores, SMC arm). Console bytes on the external AXI path are sampled
    for information only; that path is tracked separately (issue #3939).
    """

    def __init__(self, test, scoreboard) -> None:
        self.test = test
        self.sb = scoreboard
        self.dut = cocotb.top
        self.log = test.logger

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_BOOT_MAX_CYCLES", "3000000"), 0)
        heartbeat = max(1, max_cycles // 30)
        self.log.info("=" * 70)
        self.log.info("TEST: SMC-assisted real SEP boot readiness in the OSS wrapper")
        self.log.info("=" * 70)

        assert self.test.pre_release_sep_reset == 0, (
            "real-SEP profile must assert SEP reset during cold reset: "
            f"expected=0 observed={self.test.pre_release_sep_reset}"
        )
        assert self.test.pre_release_sep_fuse == 0, (
            "real-SEP profile must start with fuse-done inactive: "
            f"expected=0 observed={self.test.pre_release_sep_fuse}"
        )
        self.sb.sample_status(
            reset_n=self.test.pre_release_sep_reset,
            fuse_done=self.test.pre_release_sep_fuse,
        )

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            sep_reset = self.test.read_int(self.dut.sep_reset_n_o, "sep_reset_n_o")
            sep_fuse = self.test.read_int(
                self.dut.sep_fuse_sense_done_o, "sep_fuse_sense_done_o"
            )
            valid = self.test.read_int(self.dut.sep_trace_valid_o, "sep_trace_valid_o")
            pc = self.test.read_int(self.dut.sep_pc_o, "sep_pc_o")
            self.sb.sample_status(reset_n=sep_reset, fuse_done=sep_fuse)
            self.sb.sample_arm(
                self.test.read_int(self.dut.smc_test_pass_o, "smc_test_pass_o")
            )
            self.sb.sample_trace(valid, pc)
            self.sb.sample_windows(
                boot_rom_seen=self.test.read_int(
                    self.dut.sep_boot_rom_fetch_seen_o, "sep_boot_rom_fetch_seen_o"
                ),
                iccm_seen=self.test.read_int(
                    self.dut.sep_iccm_fetch_seen_o, "sep_iccm_fetch_seen_o"
                ),
            )
            self.sb.sample_dccm(
                self.test.read_int(
                    self.dut.sep_dccm_write_count_o, "sep_dccm_write_count_o"
                )
            )

            if self.test.read_int(self.dut.fw_char_valid_o, "fw_char_valid_o"):
                char = self.test.read_int(self.dut.fw_char_o, "fw_char_o")
                self.sb.sample_char(char)

            if self.sb.boot_ready():
                first_pc = self.test.read_int(self.dut.sep_first_pc_o, "sep_first_pc_o")
                self.log.info(
                    "SEP boot-readiness complete cycle=%d pc=0x%08x first_pc=0x%08x "
                    "traces=%d distinct_pcs=%d dccm_writes=%d console_bytes=%d",
                    cycle,
                    pc,
                    first_pc,
                    self.sb.trace_count,
                    len(self.sb.pcs),
                    self.sb.max_dccm_writes,
                    len(self.sb.console),
                )
                return

            if cycle and cycle % heartbeat == 0:
                smc_rom_reads = self.test.read_int(
                    self.dut.smc_rom_read_count_o, "smc_rom_read_count_o"
                )
                smc_pass = self.test.read_int(
                    self.dut.smc_test_pass_o, "smc_test_pass_o"
                )
                axi_writes = self.test.read_int(
                    self.dut.smu_axi_out_write_count_o, "smu_axi_out_write_count_o"
                )
                dccm_writes = self.test.read_int(
                    self.dut.sep_dccm_write_count_o, "sep_dccm_write_count_o"
                )
                self.log.info(
                    "SEP boot heartbeat cycle=%d reset=%d fuse=%d pc=0x%08x "
                    "traces=%d distinct_pcs=%d boot_rom=%s iccm=%s "
                    "dccm_writes=%d console_bytes=%d "
                    "smc_rom_reads=%d smc_arm_done=%d axi_out_writes=%d",
                    cycle,
                    sep_reset,
                    sep_fuse,
                    pc,
                    self.sb.trace_count,
                    len(self.sb.pcs),
                    self.sb.boot_rom_seen,
                    self.sb.iccm_seen,
                    dccm_writes,
                    len(self.sb.console),
                    smc_rom_reads,
                    smc_pass,
                    axi_writes,
                )
            if cycle == 100_000 and self.sb.trace_count == 0:
                raise AssertionError(
                    "SEP retired no instructions in 100000 cycles: "
                    f"reset={sep_reset} fuse={sep_fuse} pc=0x{pc:08x}"
                )
        observed_pcs = ", ".join(f"0x{pc:08x}" for pc in sorted(self.sb.pcs))
        raise AssertionError(
            f"SEP boot-readiness timeout after {max_cycles} cycles: "
            f"traces={self.sb.trace_count} distinct_pcs={len(self.sb.pcs)} "
            f"boot_rom={self.sb.boot_rom_seen} iccm={self.sb.iccm_seen} "
            f"smc_arm={self.sb.smc_arm_seen} dccm_writes={self.sb.max_dccm_writes} "
            f"pcs=[{observed_pcs}]"
        )
