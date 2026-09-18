# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP boot-ROM LSU data-read + write-ignored test (PyUVM).

Memory-subsystem rep boot-ROM LSU read. reference provenance: uvm_tests/rom
sep_rom_uvm_basic_read / sequential_read / content_verify / addr_boundary /
write_ignore. Boots the VeeR EL2 core and runs the rom_lsu_read firmware, which
does CPU LSU data loads from the boot ROM (0x1004_0000, on the dedicated
lsu_rom_axi CPU port -- unreachable by the no_cpu splice, so cpu-mode REQUIRED)
and value-checks them against a known preloaded image, then proves a store to a
ROM word is silently ignored (normal response, content unchanged -- NOT DECERR).

Distinct from sep_rom_sanity_test (which proves the IFU *executes* from
ROM): boot-ROM LSU read covers the LSU *data* read-port + the write-reject negative contract.

The boot ROM responder is preloaded with the known image via
+sep_boot_rom_hex=mem_rom_test_rom.hex (committed alongside this test, same
staging path as rom_sanity_rom.hex). Firmware-self-checking: main() returns its
error count and start.S emits the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on
the 0x8000_0000 mailbox, which the boot scoreboard gates on (plus banner + ICCM
execution). Each checker logs a positive PASS line.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "rom_lsu_read_test")
_ITCM_HEX = os.path.join(_FW_DIR, "rom_lsu_read_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "rom_lsu_read_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# A handful of ROM LSU loads + one store + re-read; the run loop early-exits on
# fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 1_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP boot ROM LSU read test"


@pyuvm.test()
class sep_boot_rom_lsu_read_test(sep_base_test):
    """Boot VeeR EL2 and run the boot-ROM LSU read + write-ignored firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
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
