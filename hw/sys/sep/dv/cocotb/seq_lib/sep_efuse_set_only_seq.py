# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU-LSU driver for one eFuse shadow word.

Set-only OR-merge policy lives in ``env/sep_efuse_set_only.py`` so the
prestage hook can import it without cocotb.
"""

from __future__ import annotations

from env.sep_efuse_image import SepEfuseImage

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver


class SepEfuseShadow(SepAxiRegDriver):
    """32-bit frontdoor read/write of one shadow-map word."""

    _DRIVER_TAG = "EFUSE"

    def _addr(self, name: str, word_idx: int) -> int:
        fld = SepEfuseImage.field(name)
        if not 0 <= word_idx < fld.n_words:
            raise ValueError(f"{name} word {word_idx} out of range 0..{fld.n_words - 1}")
        return fld.shadow_addr + 4 * word_idx

    async def read_word(self, name: str, word_idx: int) -> int:
        return await self._rd(self._addr(name, word_idx))

    async def write_word(self, name: str, word_idx: int, data: int) -> None:
        await self._wr(self._addr(name, word_idx), data & 0xFFFF_FFFF)
