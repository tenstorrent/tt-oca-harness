#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Convert a RISC-V ELF into 64-bit $readmemh VMEM format for the SEP Boot ROM.

Why ELF (not .bin)?
- The linker script places runtime .data/.bss in DCCM (VMA=0x0), but stores .data
  init bytes in ROM (LMA in ROM via AT>rom). A flat binary extracted by VMA can
  easily drop/misplace those init bytes.
- Relying purely on ELF program headers (segments) can be error-prone when AT/LMA
  is used, because the segment's p_paddr may not equal a section's true LMA.
  Instead, we:
  - place all allocatable PROGBITS sections that already live in ROM by VMA
  - place `.data` init bytes at `__data_load_start` using linker-generated symbols

Output format:
- One 64-bit word per line, little-endian packing.
- No @address directives (we emit a dense ROM image, padded to depth).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--elf", required=True, type=Path, help="Input .elf file")
    p.add_argument("--output", required=True, type=Path, help="Output .vmem file")
    p.add_argument(
        "--rom-base",
        required=True,
        type=lambda x: int(x, 0),
        help="ROM base address (e.g. 0x10000000)",
    )
    p.add_argument(
        "--depth",
        required=True,
        type=int,
        help="ROM depth in 64-bit words (pads with zeros up to this depth)",
    )
    return p.parse_args()


def _find_symbol_value(elf: ELFFile, name: str) -> int | None:
    for section in elf.iter_sections():
        if not isinstance(section, SymbolTableSection):
            continue
        for sym in section.iter_symbols():
            if sym.name == name:
                return int(sym["st_value"])
    return None


def main() -> int:
    args = parse_args()

    rom_size_bytes = args.depth * 8
    image = bytearray(b"\x00" * rom_size_bytes)

    with args.elf.open("rb") as f:
        elf = ELFFile(f)

        # 1) Place ROM-resident code/rodata sections by VMA.
        for sec in elf.iter_sections():
            hdr = sec.header
            if hdr["sh_type"] != "SHT_PROGBITS":
                continue
            if (hdr["sh_flags"] & 0x2) == 0:  # SHF_ALLOC
                continue

            addr = int(hdr["sh_addr"])
            if addr < args.rom_base:
                continue
            offset = addr - args.rom_base
            if offset >= rom_size_bytes:
                continue

            data = sec.data()
            end = min(offset + len(data), rom_size_bytes)
            image[offset:end] = data[: end - offset]

        # 2) Place `.data` init bytes at LMA (`__data_load_start`).
        data_load = _find_symbol_value(elf, "__data_load_start")
        data_start = _find_symbol_value(elf, "__data_start")
        data_end = _find_symbol_value(elf, "__data_end")
        data_sec = elf.get_section_by_name(".data")
        if (
            data_load is not None
            and data_start is not None
            and data_end is not None
            and data_sec is not None
        ):
            size = max(0, data_end - data_start)
            if size:
                data = data_sec.data()[:size]
                if data_load >= args.rom_base:
                    offset = data_load - args.rom_base
                    if offset < rom_size_bytes:
                        end = min(offset + len(data), rom_size_bytes)
                        image[offset:end] = data[: end - offset]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for i in range(0, len(image), 8):
            w = int.from_bytes(image[i : i + 8], byteorder="little", signed=False)
            out.write(f"{w:016x}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
