# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real-SEP firmware boot-readiness sequence inside the OSS SMU wrapper."""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge


class SmuSepSmokeSeq:
    """Collect reset, fetch-window, and TCM evidence until SEP boot readiness.

    The sequence finishes as soon as the scoreboard has every required
    boot-readiness evidence item (boot-ROM fetch, ICCM execution, DCCM
    stores, SMC arm); the retirement count and distinct-PC set come from
    the SEP CPU trace monitor. Console bytes on the external AXI path are
    sampled for information only.
    """

    def __init__(self, test, scoreboard) -> None:
        self.test = test
        self.sb = scoreboard
        self.dut = cocotb.top
        self.log = test.logger

    def _hier_int(self, path: str, default: int = -1) -> int:
        """Best-effort XMR read for bring-up diagnosis (missing → default)."""
        node = self.dut
        try:
            for part in path.split("."):
                node = getattr(node, part)
            return self.test.read_int(node, path, allow_xz=True)
        except Exception:
            return default

    def _probe_str(self, signal) -> str:
        value = signal.value
        if hasattr(value, "is_resolvable") and not value.is_resolvable:
            return f"X({value})"
        return str(int(value))

    def _log_sep_run_gate(self, tag: str) -> None:
        self.log.info(
            "SEP run-gate %s: cla=%s halt=%s dbg_mode=%s "
            "mpc_reset_run=%s mpc_dbg_run=%s cpu_run=%s boot_rom_reqs=%s "
            "cpu_rst_n=%s dbg_rstb=%s sep_rst_n=%s cpu_clk_cnt=%s "
            "at_release_valid=%s mpc_at_release=%s mpc_xz_at_release=%s "
            "cla_at_release=%s",
            tag,
            self._probe_str(self.dut.sep_cla_custom_o),
            self._probe_str(self.dut.sep_halt_status_o),
            self._probe_str(self.dut.sep_debug_mode_o),
            self._probe_str(self.dut.sep_mpc_reset_run_o),
            self._probe_str(self.dut.sep_mpc_debug_run_o),
            self._probe_str(self.dut.sep_cpu_run_req_o),
            self._probe_str(self.dut.sep_boot_rom_req_count_o),
            self._probe_str(self.dut.sep_cpu_rst_ni_o),
            self._probe_str(self.dut.sep_dbg_rstb_o),
            self._probe_str(self.dut.sep_mod_rst_ni_o),
            self._probe_str(self.dut.sep_cpu_clk_count_o),
            self._probe_str(self.dut.sep_rungate_at_release_valid_o),
            self._probe_str(self.dut.sep_mpc_reset_run_at_release_o),
            self._probe_str(self.dut.sep_mpc_xz_at_release_o),
            self._probe_str(self.dut.sep_cla_at_release_o),
        )

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
            # SEP EL2 trace/PC stay X until the CPU leaves reset; treat as 0.
            sep_reset = self.test.read_int(self.dut.sep_reset_n_o, "sep_reset_n_o", allow_xz=True)
            sep_fuse = self.test.read_int(
                self.dut.sep_fuse_sense_done_o, "sep_fuse_sense_done_o", allow_xz=True
            )
            pc = self.test.read_int(self.dut.sep_pc_o, "sep_pc_o", allow_xz=True)
            self.sb.sample_status(reset_n=sep_reset, fuse_done=sep_fuse)
            self.sb.sample_arm(self.test.read_int(self.dut.smc_test_pass_o, "smc_test_pass_o"))
            self.sb.sample_windows(
                boot_rom_seen=self.test.read_int(
                    self.dut.sep_boot_rom_fetch_seen_o,
                    "sep_boot_rom_fetch_seen_o",
                    allow_xz=True,
                ),
                iccm_seen=self.test.read_int(
                    self.dut.sep_iccm_fetch_seen_o,
                    "sep_iccm_fetch_seen_o",
                    allow_xz=True,
                ),
            )
            self.sb.sample_dccm(
                self.test.read_int(
                    self.dut.sep_dccm_write_count_o,
                    "sep_dccm_write_count_o",
                    allow_xz=True,
                )
            )

            if self.test.read_int(self.dut.fw_char_valid_o, "fw_char_valid_o", allow_xz=True):
                char = self.test.read_int(self.dut.fw_char_o, "fw_char_o", allow_xz=True)
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
                smc_pass = self.test.read_int(self.dut.smc_test_pass_o, "smc_test_pass_o")
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
                self._log_sep_run_gate(f"heartbeat@{cycle}")
            # The SEP runs on its default run gate, independent of the SMC
            # arm image; once that image has reported, a SEP out of reset that
            # retires nothing for 100k cycles is diagnosed rather than timed out.
            if sep_reset and self.sb.smc_arm_seen and self.sb.trace_count == 0:
                self._post_arm_idle = getattr(self, "_post_arm_idle", 0) + 1
                if self._post_arm_idle == 1:
                    self._log_sep_run_gate("arm_seen")
                if self._post_arm_idle >= 100_000:
                    self._log_sep_run_gate("post_arm_timeout")
                    raise AssertionError(
                        "SEP retired no instructions within 100000 cycles after "
                        f"SMC arm: reset={sep_reset} fuse={sep_fuse} pc=0x{pc:08x}"
                    )
            else:
                self._post_arm_idle = 0
        observed_pcs = ", ".join(f"0x{pc:08x}" for pc in sorted(self.sb.pcs))
        raise AssertionError(
            f"SEP boot-readiness timeout after {max_cycles} cycles: "
            f"traces={self.sb.trace_count} distinct_pcs={len(self.sb.pcs)} "
            f"boot_rom={self.sb.boot_rom_seen} iccm={self.sb.iccm_seen} "
            f"smc_arm={self.sb.smc_arm_seen} dccm_writes={self.sb.max_dccm_writes} "
            f"pcs=[{observed_pcs}]"
        )
