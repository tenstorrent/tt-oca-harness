# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP CPU IFU/LSU local-alias-remap test (PyUVM).

Boots the VeeR EL2 core running the cpu_alias_remap firmware, which programs the
CPU-side alias window base (SEP_LOCAL_BASE=0xD000_0000, its reset value) and
proves both the LSU and the IFU local-alias-remap (hw/sys/sep/rtl/sep_cpu.sv
u_lsu/u_ifu/u_dbg axi_window_remap): an access to 0xD000_xxxx is remapped to
physical 0x1000_xxxx (SEP SRAM), while accesses outside the window pass through.
The window is a fixed 768 MiB (`hw/sys/sep/doc/memory_map.adoc` SEP Local
Alias row) positioned by the base CSR only, with target `0x1000_0000`;
REGION_SIZE does not size this window. The IFU proof fetches and executes
an instruction through the alias (the reference suite writes the IFU port
synthetically).

This MUST be a CPU-firmware test: the OSS no_cpu AXI splice is POST-remap, so a
no_cpu driver would bypass the CPU-side remapper entirely. Firmware-self-checking; start.S emits the
PASS/FAIL magic. No fuse data is read, so the testlist entry uses +skip_fuse_sense.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
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
    """Boot VeeR EL2 and run the CPU IFU/LSU local-alias-remap firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
