#!/usr/bin/env python3
"""Convert ELF loadable segments to 64-bit VMEM format for $readmemh.

Extracts all loadable segments within the ROM address range from an ELF file
and produces a VMEM file compatible with Verilog $readmemh on a 64-bit-wide
memory array (e.g. prim_rom in sep_ip_integration.sv).

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
import subprocess
import sys


def read_elf_segments(elf_path, gcc_prefix="riscv64-unknown-elf"):
    """Read loadable segments from ELF using objcopy -O binary per segment."""
    # Use readelf to get segment info
    result = subprocess.run(
        [f"{gcc_prefix}-readelf", "-l", elf_path],
        capture_output=True, text=True, check=True
    )

    segments = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0] == "LOAD":
            # LOAD offset vaddr paddr filesz memsz flags align
            vaddr = int(parts[2], 16)
            filesz = int(parts[4], 16)
            segments.append((vaddr, filesz))

    return segments


def elf_to_binary(elf_path, output_path, gcc_prefix="riscv64-unknown-elf"):
    """Convert ELF to flat binary using objcopy."""
    subprocess.run(
        [f"{gcc_prefix}-objcopy", "-O", "binary", elf_path, output_path],
        check=True
    )


def main():
    parser = argparse.ArgumentParser(
        description="Convert ELF to 64-bit VMEM for Boot ROM preload"
    )
    parser.add_argument("elf", help="Input ELF file")
    parser.add_argument("-o", "--output", required=True, help="Output VMEM file")
    parser.add_argument("--base", required=True,
                        help="ROM base address (hex, e.g. 0x10040000)")
    parser.add_argument("--gcc-prefix", default="riscv64-unknown-elf",
                        help="GCC toolchain prefix")
    args = parser.parse_args()

    rom_base = int(args.base, 0)

    # Get loadable segment info to find the lowest load address
    segments = read_elf_segments(args.elf, args.gcc_prefix)
    if not segments:
        print("ERROR: No LOAD segments found in ELF", file=sys.stderr)
        sys.exit(1)

    # objcopy -O binary produces a flat image starting from the lowest LMA.
    # We need to know what that lowest address is to compute ROM offsets.
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_bin = tmp.name

    try:
        elf_to_binary(args.elf, tmp_bin, args.gcc_prefix)

        with open(tmp_bin, "rb") as f:
            raw = f.read()
    finally:
        os.unlink(tmp_bin)

    if not raw:
        print("ERROR: Empty binary output", file=sys.stderr)
        sys.exit(1)

    # The binary starts at the lowest segment VMA.  Find segments in ROM range.
    min_vaddr = min(s[0] for s in segments)

    # Calculate the ROM portion of the binary
    rom_offset_in_bin = rom_base - min_vaddr
    if rom_offset_in_bin < 0:
        # ROM base is below the lowest segment — segments might start at ROM base
        rom_offset_in_bin = 0

    # Extract the ROM portion
    rom_data = raw[rom_offset_in_bin:]

    # Pad to 8-byte alignment
    if len(rom_data) % 8 != 0:
        rom_data += b'\x00' * (8 - len(rom_data) % 8)

    # Write VMEM: one 64-bit LE word per line
    with open(args.output, "w") as f:
        f.write("@0000\n")
        for i in range(0, len(rom_data), 8):
            word = struct.unpack_from("<Q", rom_data, i)[0]
            f.write(f"{word:016x}\n")

    n_words = len(rom_data) // 8
    print(f"Generated {args.output}: {n_words} 64-bit words "
          f"({len(rom_data)} bytes) from {args.elf}")


if __name__ == "__main__":
    main()
