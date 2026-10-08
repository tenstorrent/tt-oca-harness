# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU LSU loads from the boot ROM return the staged image, and a store to a ROM word is ignored.

OCAH provenance: ``sep_rom_uvm_basic_read``, ``sep_rom_uvm_sequential_read``,
``sep_rom_uvm_content_verify``, ``sep_rom_uvm_addr_boundary`` and
``sep_rom_uvm_write_ignore`` check basic, sequential, content and boundary
reads and ignored writes.

The test boots the VeeR EL2 core and runs the rom_lsu_read firmware. The firmware does CPU LSU data
loads from the boot ROM (0x1004_0000, on the dedicated lsu_rom_axi CPU port). The
no_cpu splice cannot reach that port, so the test needs cpu mode. The firmware
value-checks the loads against a known preloaded image. Then it proves that a store
to a ROM word is ignored: the response is normal (not DECERR) and the content does
not change.

Distinct from sep_rom_sanity_test (which proves the IFU *executes* from
ROM): this test covers the LSU *data* read port and the write-ignored negative contract.

The boot ROM responder is preloaded with the known image via
+sep_boot_rom_hex=mem_rom_test_rom.hex (committed alongside this test, same
staging path as rom_sanity_rom.hex). Firmware-self-checking: main() returns its
error count and fw/startup/crt0.s emits the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on
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
    """Boot-ROM LSU loads match the staged image, and a ROM store leaves the content unchanged."""

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
