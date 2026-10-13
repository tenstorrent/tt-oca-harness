# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot ROM image writer and the ROM bit-flip hook driver.

The boot ROM macro (``sep_ip_integration`` ``u_sep_boot_rom``, a ``prim_rom``)
holds 8192 words of 64 bits for the 64 KiB aperture at 0x1004_0000. Word ``i``
holds bytes ``8*i`` to ``8*i+7`` of the aperture, little-endian: byte offset 0
is bits 7:0. ``tb_backdoor_mem`` loads it at time 0 from ``+sep_boot_rom_hex``
(``$readmemh``, one 16-digit word per line, word 0 first).

The module has no simulator import at load time, so the pre-sim stage hook
(``cocotb/dv_sim_prestage.py``) can write an image before the simulator starts.

Words 0 to ``STUB_WORDS - 1`` hold the boot stub, which the leaf supplies as
32-bit instructions; the default stub is ``jal x0, 0`` (a spin loop) followed by
``addi x0, x0, 0`` (nop).

Usage::

    img = SepRomImage(stub=[...])
    img.randomize(rng, first=STUB_WORDS, last=ROM_WORDS - 2)
    img.write_hex(path)
    ...
    await rom_flip(dut, index, 1 << bit)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

ROM_BASE = 0x1004_0000
ROM_BYTES = 64 * 1024
ROM_WORD_BYTES = 8
ROM_WORDS = ROM_BYTES // ROM_WORD_BYTES
STUB_WORDS = 16

INSN_SPIN = 0x0000_006F  # jal x0, 0
INSN_NOP = 0x0000_0013  # addi x0, x0, 0
_MASK64 = (1 << 64) - 1


class SepRomImage:
    """A full boot ROM image of ``ROM_WORDS`` 64-bit words."""

    def __init__(self, stub: Iterable[int] | None = None, fill: int = 0) -> None:
        self.words = [fill & _MASK64] * ROM_WORDS
        insns = list(stub) if stub is not None else [INSN_SPIN]
        if len(insns) > 2 * STUB_WORDS:
            raise ValueError(f"the boot stub holds at most {2 * STUB_WORDS} instructions")
        insns += [INSN_NOP] * (2 * STUB_WORDS - len(insns))
        self.place_insns(0, insns)

    def _set_insn(self, slot: int, insn: int) -> None:
        word, half = divmod(slot, 2)
        shift = 32 * half
        self.words[word] = (self.words[word] & ~(0xFFFF_FFFF << shift) & _MASK64) | (
            (insn & 0xFFFF_FFFF) << shift
        )

    def place_insns(self, byte_offset: int, insns: list[int]) -> None:
        """Place 32-bit instructions from a 4-byte aligned ``byte_offset``."""
        if byte_offset % 4:
            raise ValueError("instruction offset must be 4-byte aligned")
        if byte_offset + 4 * len(insns) > ROM_BYTES:
            raise ValueError("instructions run past the end of the ROM")
        for k, insn in enumerate(insns):
            self._set_insn(byte_offset // 4 + k, insn)

    def set_word(self, index: int, value: int) -> None:
        self.words[index] = value & _MASK64

    def word(self, index: int) -> int:
        return self.words[index]

    def read(self, addr: int, size: int) -> int:
        """The little-endian value of ``size`` bytes at aperture address ``addr``."""
        off = addr - ROM_BASE
        if not 0 <= off <= ROM_BYTES - size:
            raise ValueError(f"address 0x{addr:08x} is outside the boot ROM aperture")
        val = 0
        for b in range(size):
            word, lane = divmod(off + b, ROM_WORD_BYTES)
            val |= ((self.words[word] >> (8 * lane)) & 0xFF) << (8 * b)
        return val

    def randomize(self, rng, *, first: int = STUB_WORDS, last: int = ROM_WORDS - 1) -> None:
        """Fill words ``first`` to ``last`` (inclusive) from ``rng`` (a ``SepSeededRng``)."""
        for i in range(first, last + 1):
            self.words[i] = rng.getrandbits(64)

    def flipped(self, index: int, mask: int) -> int:
        """Word ``index`` with ``mask`` XORed in, the value after a ROM bit-flip."""
        return (self.words[index] ^ mask) & _MASK64

    def hex_lines(self) -> list[str]:
        return [f"{w:016x}" for w in self.words]

    def write_hex(self, path: str | Path) -> Path:
        """Write the ``$readmemh`` file; returns its path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(self.hex_lines()) + "\n")
        return p


async def rom_flip(dut, index: int, mask: int) -> None:
    """Pulse the ROM bit-flip hook: XOR ``mask`` into stored word ``index``."""
    from cocotb.triggers import Timer

    if not 0 <= index < ROM_WORDS:
        raise ValueError(f"ROM word index {index} out of range")
    dut.rom_flip_index_i.value = index
    dut.rom_flip_mask_i.value = mask & _MASK64
    await Timer(1, units="ns")
    dut.rom_flip_i.value = 1
    await Timer(1, units="ns")
    dut.rom_flip_i.value = 0
    await Timer(1, units="ns")


if __name__ == "__main__":
    # Self-check of the layout (no simulator).
    img = SepRomImage()
    assert img.word(0) == (INSN_NOP << 32) | INSN_SPIN
    assert img.read(ROM_BASE, 4) == INSN_SPIN
    assert img.read(ROM_BASE + 4, 4) == INSN_NOP
    img.set_word(5, 0x0123_4567_89AB_CDEF)
    assert img.read(ROM_BASE + 40, 1) == 0xEF
    assert img.read(ROM_BASE + 41, 2) == 0xABCD
    assert img.read(ROM_BASE + 44, 4) == 0x0123_4567
    assert img.flipped(5, 1) == 0x0123_4567_89AB_CDEE
    assert len(img.hex_lines()) == ROM_WORDS
    print("sep_rom_image self-check PASS")
