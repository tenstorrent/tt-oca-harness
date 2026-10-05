# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The IFU fetches and executes seven boot-ROM functions, and each returns its expected value.

The test boots VeeR EL2 from ICCM with the rom_sanity firmware. The firmware calls seven
hand-assembled functions in the boot-ROM (0x1004_0000) through function pointers, so the IFU
fetches and executes them from ROM. Each return value is checked
(42/123/100/0xDEADBEEF/55/77/42), covering I/U/R/J-type and NOP-sled sequential fetch.

``+sep_boot_rom_hex=rom_sanity_rom.hex`` preloads the boot-ROM responder with the committed ROM
image. fw/startup/crt0.s emits PASS/FAIL magic from main()'s error count, which the boot
scoreboard gates on with the banner and ICCM-execution checks.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "rom_sanity_test")
_ITCM_HEX = os.path.join(_FW_DIR, "rom_sanity_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "rom_sanity_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# The firmware calls seven ROM functions and prints one line for each.
_EXPECTED_IFU_CHECKS = 7
# The run loop exits early on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 1_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP ROM IFU sanity test"


@pyuvm.test()
class sep_rom_sanity_test(sep_base_test):
    """Seven ROM-resident calls return their expected values, one IFU check line each."""

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

        # The PASS/FAIL magic only tells us the firmware finished with errors==0. It
        # cannot tell us how many checks ran, so a firmware that silently stopped
        # calling into the ROM after two functions would still pass. Count the
        # per-function lines the firmware emits and require all seven.
        console = self.sb.console_text()
        seen = console.count("[PASS] IFU")
        assert seen == _EXPECTED_IFU_CHECKS, (
            f"expected {_EXPECTED_IFU_CHECKS} ROM IFU function checks in the console, saw {seen}"
        )
        assert "PASS: 7/7" in console, "firmware did not report the 7/7 summary"
        self.logger.info(
            "CHK-ALL PASS: confirmed host-side, %d/%d ROM IFU function checks present in the console",
            seen,
            _EXPECTED_IFU_CHECKS,
        )
