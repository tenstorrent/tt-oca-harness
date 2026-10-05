#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Convert ELF ROM sections to 64-bit VMEM format for $readmemh.

Extracts allocatable ELF sections whose *load address* (LMA) falls in the Boot
ROM window and produces a VMEM file compatible with Verilog $readmemh on a
64-bit-wide memory array (e.g. prim_rom in sep_ip_integration.sv).

Sections are placed by LMA, not VMA: .data executes from DCCM (VMA in DCCM) but
its initial image is stored in Boot ROM (LMA via the linker `AT> rom`), so it
must land in the ROM image at its load address.

ELF parsing uses pyelftools (already a build/test dependency, e.g.
fw/sep/tests/common_otbn/generate_otbn_c.py and tools/elf_to_vmem64.py) rather
than shelling out to readelf/objcopy.

Output format:
  @0000
  <16-digit hex word>   // 64-bit little-endian word at offset 0
  <16-digit hex word>   // 64-bit little-endian word at offset 8
  ...

Usage:
  python3 elf-to-vmem.py --base 0x10040000 -o boot_rom.vmem boot_rom.elf
"""

import argparse
import struct
import sys

from elftools.elf.elffile import ELFFile

_SHF_ALLOC = 0x2


def read_load_segments(elf):
    """Return [(vaddr, paddr, memsz), ...] for PT_LOAD program headers.

    Used to map a section's VMA to its load address (LMA). A section whose VMA
    lives in DCCM but whose initial image is stored in ROM (linker `AT> rom`)
    has PhysAddr != VirtAddr; placing the vmem by LMA puts that image at its ROM
    load address."""
    segments = []
    for seg in elf.iter_segments():
        if seg.header["p_type"] != "PT_LOAD":
            continue
        segments.append((int(seg["p_vaddr"]), int(seg["p_paddr"]), int(seg["p_memsz"])))
    return segments


def vma_to_lma(vma, segments):
    """Map a section VMA to its load address using the containing LOAD segment."""
    for vaddr, paddr, memsz in segments:
        if vaddr <= vma < vaddr + memsz:
            return vma - vaddr + paddr
    return vma  # identity fallback (VMA == LMA)


def read_rom_sections(elf, rom_base, rom_end, segments):
    """Return allocatable PROGBITS sections whose LMA lies in [rom_base, rom_end),
    each as {name, lma, data}."""
    sections = []
    for sec in elf.iter_sections():
        hdr = sec.header
        if hdr["sh_type"] != "SHT_PROGBITS":
            continue
        if (hdr["sh_flags"] & _SHF_ALLOC) == 0:
            continue
        data = sec.data()
        if not data:
            continue
        lma = vma_to_lma(int(hdr["sh_addr"]), segments)
        if rom_base <= lma < rom_end:
            sections.append({"name": sec.name, "lma": lma, "data": data})
    return sections


def main():
    parser = argparse.ArgumentParser(description="Convert ELF to 64-bit VMEM for Boot ROM preload")
    parser.add_argument("elf", help="Input ELF file")
    parser.add_argument("-o", "--output", required=True, help="Output VMEM file")
    parser.add_argument("--base", required=True, help="ROM base address (hex, e.g. 0x10040000)")
    parser.add_argument("--size", default="0x10000", help="ROM size in bytes (default: 0x10000)")
    # Accepted for CLI compatibility with callers that still pass it; ELF parsing
    # no longer invokes the toolchain, so the value is unused.
    parser.add_argument(
        "--gcc-prefix",
        default="riscv64-unknown-elf",
        help="(deprecated, unused) GCC toolchain prefix",
    )
    args = parser.parse_args()

    rom_base = int(args.base, 0)
    rom_size = int(args.size, 0)
    rom_end = rom_base + rom_size

    with open(args.elf, "rb") as f:
        elf = ELFFile(f)
        segments = read_load_segments(elf)
        sections = read_rom_sections(elf, rom_base, rom_end, segments)

    if not sections:
        print("ERROR: No ROM sections found in ELF", file=sys.stderr)
        sys.exit(1)

    rom_data = bytearray(rom_size)
    highest_used = 0
    for sec in sections:
        offset = sec["lma"] - rom_base
        end = offset + len(sec["data"])
        if end > rom_size:
            print(
                f"ERROR: Section {sec['name']} exceeds ROM range "
                f"0x{rom_base:08x}..0x{rom_end - 1:08x}",
                file=sys.stderr,
            )
            sys.exit(1)
        rom_data[offset:end] = sec["data"]
        highest_used = max(highest_used, end)

    # Pad to 8-byte alignment
    output_size = highest_used
    if output_size % 8 != 0:
        output_size += 8 - (output_size % 8)
    rom_data = rom_data[:output_size]

    # Write VMEM: one 64-bit LE word per line
    with open(args.output, "w") as f:
        f.write("@0000\n")
        for i in range(0, len(rom_data), 8):
            word = struct.unpack_from("<Q", rom_data, i)[0]
            f.write(f"{word:016x}\n")

    n_words = len(rom_data) // 8
    print(
        f"Generated {args.output}: {n_words} 64-bit words ({len(rom_data)} bytes) from {args.elf}"
    )


if __name__ == "__main__":
    main()
