# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ICCM pad fill leaves the top of SEP SRAM alone.

Extends ``sep_manifest_magic_survives_handoff_test`` with the last SEP SRAM word, which no
step of a good boot writes. The test writes a sentinel there before the boot, through the
Verilator public scope (``env/sep_mem_backdoor.py``), and requires it unchanged when
``BL1_COPIED`` is printed, after the ``[S29]`` pad and the BL1 copy.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Immediate
from env import sep_mem_backdoor as mem
from env.sep_rom_console import wait_for_line
from rom_fw.sep_manifest_magic_survives_handoff_test import (
    sep_manifest_magic_survives_handoff_test,
)

# Printed after the BL1 copy, which follows the pad. No DMA writes SEP SRAM after it.
_BL1_COPIED = "BL1_COPIED"
_SENTINEL = 0xC0FF_EE5A_A5EE_FF0C


@pyuvm.test()
class sep_iccm_pad_sram_top_intact_test(sep_manifest_magic_survives_handoff_test):
    """Boot normally; the last SEP SRAM word still holds its sentinel at BL1_COPIED."""

    _last_at_copied: int | None = None

    async def _watch_last_word(self, console: list[str]) -> None:
        await wait_for_line(console, _BL1_COPIED)
        self._last_at_copied = int(self._sram[mem.SRAM_WORDS - 1].value)

    def start_watchers(self, console: list[str]) -> None:
        cocotb.start_soon(self._watch_last_word(console))

    async def run_scenario(self) -> None:
        self._last_at_copied = None
        self._sram = mem.sram_array()
        self._sram[mem.SRAM_WORDS - 1].value = Immediate(_SENTINEL)
        assert int(self._sram[mem.SRAM_WORDS - 1].value) == _SENTINEL, "the sentinel did not stick"
        await super().run_scenario()

    def check_transport(self, console, flash) -> None:
        super().check_transport(console, flash)
        last = mem.SRAM_WORDS - 1
        assert self._last_at_copied is not None, (
            f"{_BL1_COPIED} never reached the console, so the last SRAM word was never sampled"
        )
        assert self._last_at_copied == _SENTINEL, (
            f"SEP SRAM word {last} (byte 0x{mem.SRAM_BASE + last * mem.SRAM_WORD_BYTES:08x}) "
            f"read 0x{self._last_at_copied:016x} at {_BL1_COPIED}, expected the sentinel "
            f"0x{_SENTINEL:016x}; something wrote the top of SEP SRAM during the hand-off"
        )
        self.logger.info(
            "CHK-SRAM-TOP-INTACT PASS: word %d still 0x%016x at %s",
            last,
            self._last_at_copied,
            _BL1_COPIED,
        )
