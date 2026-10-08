# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU LSU and IFU accesses at 0xD000_xxxx reach SEP SRAM at 0x1000_xxxx; others pass through.

OCAH provenance: ``sep_cpu_ifu_lsu_alias_remap_matrix_test`` checks IFU and
LSU local-alias remapping.

The test boots VeeR EL2 with the cpu_alias_remap firmware. The firmware programs the CPU-side
alias window base (SEP_LOCAL_BASE_ADDR = 0xD000_0000, its reset value) and checks the LSU and
IFU remap in hw/sys/sep/rtl/sep_cpu.sv (axi_window_remap): 0xD000_xxxx maps to SEP SRAM at
0x1000_xxxx and accesses outside the window pass through. The window is a fixed 768 MiB
(memory_map.adoc, SEP Local Alias) positioned by the base CSR only; REGION_SIZE does not size
it. The IFU check fetches and executes an instruction through the alias.

This must be a CPU-firmware test: the no_cpu AXI splice is after the remap, so a no_cpu driver
bypasses the remapper. Firmware-self-checking (fw/startup/crt0.s PASS/FAIL magic); no fuse data
is read, so the testlist entry uses +skip_fuse_sense.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_fabric_tap import SepFabricTap, log_axprot
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "cpu_alias_remap_test")
_ITCM_HEX = os.path.join(_FW_DIR, "cpu_alias_remap_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "cpu_alias_remap_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP CPU IFU/LSU alias-remap test"


@pyuvm.test()
class sep_cpu_ifu_lsu_alias_remap_matrix_test(sep_base_test):
    """Alias-window LSU and IFU accesses reach SEP SRAM; other accesses pass through unchanged."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        # Log-only: the AxPROT the core drives on IFU fetches.
        cpu_ifu = SepFabricTap("PR-CPU-IFU", xz_fail=False).start()
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                _DTCM_HEX,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
        finally:
            await cpu_ifu.stop()
            log_axprot(self.logger, cpu_ifu, "ifu", "ar", "M")
