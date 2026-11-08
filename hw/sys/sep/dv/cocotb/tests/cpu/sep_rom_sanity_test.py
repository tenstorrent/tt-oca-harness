# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The IFU fetches and executes seven boot-ROM functions repeatedly, and each call returns its value.

The test boots VeeR EL2 from ICCM with the rom_sanity firmware. The firmware calls seven
hand-assembled functions in the boot-ROM (0x1004_0000) through function pointers, so the IFU
fetches and executes them from ROM, and runs the seven calls in three iterations. The core has
no instruction cache, so each call fetches its body from ROM again. Each return value is
checked (42/123/100/0xDEADBEEF/55/77/43), covering I/U/R/J-type and NOP-sled sequential fetch.

Checks:
  CHK-IFU-TYPES  : firmware, one line per call: ``<name> k=<iteration> got= want=``.
  CHK-IFU-REPEAT : host side, the console holds one CHK-IFU-TYPES PASS line for each of
                   the seven functions in each iteration k = 1..3 (21 lines, seven distinct
                   names per iteration, the same names in every iteration), no
                   CHK-IFU-TYPES FAIL line, and the firmware summary ``PASS: 21/21``.

``+sep_boot_rom_hex=rom_sanity_rom.hex`` preloads the boot-ROM responder with the committed ROM
image. fw/startup/crt0.s emits PASS/FAIL magic from main()'s error count, which the boot
scoreboard gates on with the banner and ICCM-execution checks.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
import re
from collections import Counter
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
# The firmware calls seven ROM functions in each of three iterations and prints one line
# per call (ROM_FUNCS and ROM_CALL_ITERATIONS in rom_sanity_test.c).
_ROM_FUNCS = 7
_ITERATIONS = 3
_EXPECTED_IFU_CHECKS = _ROM_FUNCS * _ITERATIONS
_IFU_LINE = re.compile(r"CHK-IFU-TYPES (PASS|FAIL): (.+?) k=(\d+) got=")
# The run loop exits early on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 1_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP ROM IFU sanity test"


@pyuvm.test()
class sep_rom_sanity_test(sep_base_test):
    """Seven ROM-resident calls in three iterations return their values, one line per call."""

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
        # calling into the ROM would still pass. Count the per-call lines.
        console = self.sb.console_text()
        lines = _IFU_LINE.findall(console)
        passed = [(name, int(k)) for verdict, name, k in lines if verdict == "PASS"]
        fails = sum(1 for verdict, _name, _k in lines if verdict == "FAIL")
        per_k = Counter(k for _name, k in passed)
        names = {k: {name for name, kk in passed if kk == k} for k in range(1, _ITERATIONS + 1)}
        cells = Counter(passed)
        summary = f"PASS: {_EXPECTED_IFU_CHECKS}/{_EXPECTED_IFU_CHECKS} " in console
        ok = (
            fails == 0
            and len(passed) == _EXPECTED_IFU_CHECKS
            and set(per_k) == set(range(1, _ITERATIONS + 1))
            and all(len(names[k]) == _ROM_FUNCS for k in names)
            and all(names[k] == names[1] for k in names)
            and all(n == 1 for n in cells.values())
            and summary
        )
        text = (
            f"iterations={_ITERATIONS} functions={_ROM_FUNCS} "
            f"pass_lines={len(passed)}/{_EXPECTED_IFU_CHECKS} fail_lines={fails} "
            f"per_iteration={','.join(str(per_k[k]) for k in range(1, _ITERATIONS + 1))} "
            f"distinct_names={len(names[1])} summary={int(summary)}"
        )
        if not ok:
            self.logger.error("CHK-IFU-REPEAT FAIL: %s", text)
            raise AssertionError(f"CHK-IFU-REPEAT FAIL: {text}")
        self.logger.info("CHK-IFU-REPEAT PASS: %s", text)
        self.logger.info(
            "CHK-ALL PASS: confirmed host-side, %d/%d ROM IFU call checks present in the console",
            len(passed),
            _EXPECTED_IFU_CHECKS,
        )
