# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Patch a firmware parameter block into a staged DTCM image at a magic sentinel.

Lets a cocotb test be the single source of randomness for a CPU-firmware test
without needing the .map: the firmware declares a ``volatile`` block whose first
word is a unique non-ASCII magic, and the test byte-searches the $readmemh DTCM
image for that magic and overwrites the following words. CPU-firmware reps
(SPI flash command, SPI DMA-TX, DMA basic) seed legal address/length/data per
run while reusing one compiled firmware image.
"""

from __future__ import annotations

import os


def parse_hex_cells(path: str) -> dict:
    """Parse a Verilog $readmemh byte image into {byte_addr: value}."""
    cells: dict = {}
    addr = 0
    with open(path) as fh:
        for line in fh:
            tok = line.strip()
            if not tok:
                continue
            if tok.startswith("@"):
                addr = int(tok[1:], 16)
                continue
            for byte in tok.split():
                cells[addr] = int(byte, 16)
                addr += 1
    return cells


def find_magic(cells: dict, magic_le: bytes) -> int:
    """Return the byte address where the little-endian magic bytes start."""
    for base in sorted(cells):
        if all(cells.get(base + i) == magic_le[i] for i in range(len(magic_le))):
            return base
    raise RuntimeError("param-block magic not found in DTCM image")


def _rewrite(src: str, dst: str, patches: dict) -> None:
    """Rewrite ``src`` to ``dst`` replacing the bytes in ``patches`` (addr->byte),
    preserving the original @addr / 16-byte-per-line layout exactly."""
    out = []
    addr = 0
    with open(src) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            tok = line.strip()
            if tok.startswith("@"):
                addr = int(tok[1:], 16)
                out.append(line)
                continue
            if not tok:
                out.append(line)
                continue
            new_toks = []
            for byte in tok.split():
                new_toks.append(f"{patches[addr]:02X}" if addr in patches else byte)
                addr += 1
            out.append(" ".join(new_toks))
    with open(dst, "w") as fh:
        fh.write("\n".join(out) + "\n")


def patch_param_block(src_hex: str, dst_hex: str, magic: int, words: list) -> None:
    """Write ``words`` (a list of 32-bit ints, magic first) into ``src_hex`` at the
    ``magic`` sentinel, emitting the patched image to ``dst_hex``."""
    cells = parse_hex_cells(src_hex)
    base = find_magic(cells, magic.to_bytes(4, "little"))
    patches = {}
    for k, word in enumerate(words):
        for b in range(4):
            patches[base + 4 * k + b] = (word >> (8 * b)) & 0xFF
    missing = sorted(a for a in patches if a not in cells)
    if missing:
        raise RuntimeError(
            f"param block of {len(words)} words at 0x{base:x} runs past the DTCM image: "
            f"first unbacked byte 0x{missing[0]:x}"
        )
    os.makedirs(os.path.dirname(dst_hex) or ".", exist_ok=True)
    _rewrite(src_hex, dst_hex, patches)
