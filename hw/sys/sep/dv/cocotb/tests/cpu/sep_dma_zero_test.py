# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The Secure-DMA zero fill clears SEP SRAM, DCCM and ICCM, and a sub-word ICCM fill is rejected.

The dma_zero_test firmware drives the zero fill (CONTROL.OPCODE 4) into SEP SRAM at 4-byte and
1-byte width, into a DCCM buffer and into ICCM, the last two through the core's DMA slave port,
and checks the cleared bytes and their neighbours. ICCM is read back through a DMA copy to SRAM.
A 2-byte-wide fill into ICCM must end in BUS_ERROR with the exclusive host-path error, because the
core accepts only whole words there. The firmware returns its error count and fw/startup/crt0.s
emits PASS/FAIL magic that the boot scoreboard gates on.

The host gates on each checker's PASS line, so an image without a leg fails here rather than at
the PASS magic. The core's DMA slave port exists only on the full-CPU target, which is why the
TCM legs live in firmware and not in the no_cpu ``sep_dma_zero_fill_rand_test``.

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
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_zero_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_zero_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_zero_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Five short fills and two 72-byte copies; the run loop early-exits on fw_done, so this is an
# upper bound.
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA zero fill test"
_CHECKS = (
    ("PASS: CHK-ZERO-SRAM ", "CHK-ZERO-SRAM", "the SRAM word and byte fills"),
    ("PASS: CHK-ZERO-DCCM ", "CHK-ZERO-DCCM", "the DCCM fill through the core's DMA port"),
    ("PASS: CHK-ZERO-ICCM ", "CHK-ZERO-ICCM", "the ICCM fill through the core's DMA port"),
    (
        "PASS: CHK-ZERO-TCM-NARROW ",
        "CHK-ZERO-TCM-NARROW",
        "the rejected 2-byte-wide ICCM fill and its recovery",
    ),
)


@pyuvm.test()
class sep_dma_zero_test(sep_base_test):
    """Zero fills clear SRAM, DCCM and ICCM; a sub-word ICCM fill ends in BUS_ERROR."""

    build_env = False
    required_evidence = tuple(chk for _, chk, _ in _CHECKS)

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
        console = self.sb.console_text()
        for needle, chk, what in _CHECKS:
            assert any(ln.startswith(needle) for ln in console.splitlines()), (
                f"{chk} FAIL: firmware console has no {needle.strip()!r} line, so {what} did "
                f"not run or did not pass. Console was:\n{console}"
            )
            self.logger.info("%s PASS: firmware reported %s", chk, what)
