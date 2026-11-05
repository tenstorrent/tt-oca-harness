# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM's optional memory clears, built in, zero what they cover and the boot goes on.

Runs the ``boot_rom_clear`` firmware profile (``build_clear/``), the default Boot ROM with
``SRAM_SCRUB_BYTES=0x40000`` and ``ROM_ICCM_CLEAR_FULL=1``: at ``[S15]`` the ROM zeroes all
of SEP SRAM, and at ``[S16]`` all of ICCM, each with one secure DMA zero fill. The ICCM
clear takes the place of the pad past BL1 that the default build writes at hand-off.

Before the boot the test writes a non-zero word to every SEP SRAM word and every ICCM row,
so a clear that never ran cannot pass on memory that happened to be zero. Nothing is
preloaded into SEP SRAM for the boot itself: the manifest comes over SPI after the scrub.
When ``SRAM_CLR_OK`` reaches the console it requires every SEP SRAM word to be zero. When
``BL1_COPIED`` does, it reads every ICCM word outside the span BL1 was copied to
(``COPY_DST=`` and ``COPY_LEN=``) and requires each to be zero. The arrays are read
through the Verilator public scope (``env/sep_mem_backdoor.py``).
"""

from __future__ import annotations

import re

import cocotb
import pyuvm
from cocotb.handle import Immediate
from env import sep_mem_backdoor as mem
from env.sep_rom_console import wait_for_line
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_SRAM_CLR_OK = "SRAM_CLR_OK"
_ICCM_CLR_FULL = "ICCM_CLR_FULL"
_ICCM_PAD = "ICCM_PAD="
_BL1_COPIED = "BL1_COPIED"
_COPY_DST = re.compile(r"COPY_DST=0x([0-9a-fA-F]+)")
_COPY_LEN = re.compile(r"COPY_LEN=0x([0-9a-fA-F]+)")

# Non-zero in the data bits of every row; the ECC bits are left wrong on purpose,
# since the clear rewrites both.
_ICCM_POISON = 0x7F_A5A5_5A5A
_SRAM_POISON = 0xA5A5_5A5A_5A5A_A5A5

# Report at most this many offending words in an assertion message.
_MAX_REPORT = 8


def _hex_field(pattern: re.Pattern, console: list[str]) -> int | None:
    for line in console:
        m = pattern.search(line)
        if m:
            return int(m.group(1), 16)
    return None


@pyuvm.test()
class sep_rom_clear_variant_test(sep_rom_ot_dma_boot_test):
    """Boot the clear-enabled ROM; memory the ROM clears reads zero afterwards."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _SRAM_CLR_OK,
        _ICCM_CLR_FULL,
        _BL1_COPIED,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (_ICCM_PAD,)

    _sram = None
    _iccm = None
    _sram_nonzero: list[tuple[int, int]] | None = None
    _iccm_nonzero: list[tuple[int, int]] | None = None
    _iccm_checked = 0
    _bl1_span: tuple[int, int] | None = None

    def _poison(self) -> None:
        for i in range(mem.SRAM_WORDS):
            self._sram[i].value = Immediate(_SRAM_POISON)
        for addr in range(mem.ICCM_BASE, mem.ICCM_BASE + mem.ICCM_BYTES, 4):
            mem.iccm_set(self._iccm, addr, _ICCM_POISON)
        assert int(self._sram[mem.SRAM_WORDS - 1].value) == _SRAM_POISON, (
            "the SEP SRAM poison did not stick"
        )
        probe = mem.ICCM_BASE + mem.ICCM_BYTES - 4
        assert mem.iccm_word(self._iccm, probe) == _ICCM_POISON & 0xFFFF_FFFF, (
            "the ICCM poison did not stick"
        )

    def _scan_sram(self) -> None:
        nonzero = []
        for i in range(mem.SRAM_WORDS):
            word = int(self._sram[i].value)
            if word != 0:
                nonzero.append((i, word))
        self._sram_nonzero = nonzero

    def _scan_iccm(self, console: list[str]) -> None:
        dst = _hex_field(_COPY_DST, console)
        length = _hex_field(_COPY_LEN, console)
        assert dst is not None and length is not None, (
            f"COPY_DST= or COPY_LEN= missing from the console: {console}"
        )
        self._bl1_span = (dst, length)
        nonzero = []
        checked = 0
        for addr in range(mem.ICCM_BASE, mem.ICCM_BASE + mem.ICCM_BYTES, 4):
            if dst <= addr < dst + length:
                continue
            checked += 1
            word = mem.iccm_word(self._iccm, addr)
            if word != 0:
                nonzero.append((addr, word))
        self._iccm_nonzero = nonzero
        self._iccm_checked = checked

    async def _watch(self, console: list[str]) -> None:
        await wait_for_line(console, _SRAM_CLR_OK)
        self._scan_sram()
        await wait_for_line(console, _BL1_COPIED)
        self._scan_iccm(console)

    def start_watchers(self, console: list[str]) -> None:
        cocotb.start_soon(self._watch(console))

    async def run_scenario(self) -> None:
        self._sram_nonzero = None
        self._iccm_nonzero = None
        self._sram = mem.sram_array()
        self._iccm = mem.iccm_banks()
        self._poison()
        await super().run_scenario()

    def check_transport(self, console, flash) -> None:
        assert self._sram_nonzero is not None, (
            f"{_SRAM_CLR_OK} reached the console but SEP SRAM was never scanned"
        )
        assert not self._sram_nonzero, (
            f"{len(self._sram_nonzero)} of {mem.SRAM_WORDS} SEP SRAM words are not zero at "
            f"{_SRAM_CLR_OK}, e.g. "
            + ", ".join(
                f"0x{mem.SRAM_BASE + i * mem.SRAM_WORD_BYTES:08x}=0x{w:016x}"
                for i, w in self._sram_nonzero[:_MAX_REPORT]
            )
        )
        self.logger.info(
            "CHK-SRAM-SCRUBBED PASS: all %d SEP SRAM words read zero at %s",
            mem.SRAM_WORDS,
            _SRAM_CLR_OK,
        )

        assert self._iccm_nonzero is not None, (
            f"{_BL1_COPIED} reached the console but ICCM was never scanned"
        )
        dst, length = self._bl1_span
        assert self._iccm_checked > 0, "the BL1 span covered all of ICCM; nothing was checked"
        assert not self._iccm_nonzero, (
            f"{len(self._iccm_nonzero)} of {self._iccm_checked} ICCM words outside BL1's span "
            f"[0x{dst:08x}, 0x{dst + length:08x}) are not zero after the full ICCM clear, "
            f"e.g. "
            + ", ".join(f"0x{a:08x}=0x{w:08x}" for a, w in self._iccm_nonzero[:_MAX_REPORT])
        )
        self.logger.info(
            "CHK-ICCM-CLEARED PASS: %d ICCM words outside BL1 [0x%08x, 0x%08x) read zero",
            self._iccm_checked,
            dst,
            dst + length,
        )
