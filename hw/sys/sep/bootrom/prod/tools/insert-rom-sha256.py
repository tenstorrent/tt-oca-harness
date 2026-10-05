#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Insert the SHA-256 hash of the ICCM (code) content into the ROM ELF.

Insert and verify the ROM SHA-256 string for reference suite.

Key behavior:
  - Works with ELF files (not flat binary).
  - Hashes only ICCM sections (.text + .metadata) via objcopy extraction.
  - Patches g_rom_sha256_str (80-byte ASCII string) in .rodata (DCCM).
  - No circular dependency: hash covers ICCM, result lives in DCCM.

Usage:
  insert-rom-sha256.py ELF                          # print hash
  insert-rom-sha256.py ELF -o OUT                   # patch and write
  insert-rom-sha256.py ELF --verify                 # verify embedded hash
  insert-rom-sha256.py ELF --gcc-prefix PREFIX ...  # specify toolchain
"""

import argparse
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile

HASH_STR_SIZE = 80  # fixed size of the embedded hash string
SYMBOL_NAME = "g_rom_sha256_str"

# ICCM sections to hash (must match Makefile ITCM_ELF_SECTIONS).
ICCM_SECTIONS = [
    "--only-section=.text",
    "--only-section=.text.*",
    "--only-section=.metadata",
    "--only-section=.metadata.*",
]


def run_cmd(cmd, check=True):
    """Run a subprocess and return stdout."""
    logging.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    if result.returncode != 0 and check:
        logging.error("Command failed: %s\nstderr: %s", " ".join(cmd), result.stderr)
    return result.stdout


def extract_iccm_binary(elf_path, gcc_prefix, tmpdir):
    """Extract ICCM sections as a flat binary and return its bytes."""
    objcopy = f"{gcc_prefix}-objcopy"
    tmp_bin = os.path.join(tmpdir, "iccm.bin")
    cmd = [objcopy, "-O", "binary"] + ICCM_SECTIONS + [elf_path, tmp_bin]
    run_cmd(cmd)
    with open(tmp_bin, "rb") as f:
        return f.read()


def find_symbol_vma(elf_path, gcc_prefix, symbol):
    """Find a symbol's VMA (virtual memory address) using nm."""
    nm = f"{gcc_prefix}-nm"
    output = run_cmd([nm, elf_path])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == symbol:
            return int(parts[0], 16)
    return None


def find_section_info(elf_path, gcc_prefix, section_name):
    """Find a section's VMA and file offset using readelf."""
    readelf = f"{gcc_prefix}-readelf"
    output = run_cmd([readelf, "-S", "-W", elf_path])
    # readelf -S -W output format (wide):
    # [Nr] Name     Type     Addr     Off    Size   ES Flg Lk Inf Al
    for line in output.splitlines():
        # Match lines like: [ 3] .rodata  PROGBITS  00080000 001234 000100 ...
        m = re.match(
            r"\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)",
            line,
        )
        if m and m.group(1) == section_name:
            vma = int(m.group(2), 16)
            file_offset = int(m.group(3), 16)
            size = int(m.group(4), 16)
            return vma, file_offset, size
    return None, None, None


def compute_hash(iccm_data):
    """Compute SHA-256 of ICCM binary data and return the formatted string."""
    h = hashlib.sha256(iccm_data)
    hash_str = f"sha256:{h.hexdigest()}"
    logging.debug(hash_str)
    return hash_str


def format_hash_bytes(hash_str):
    """Encode hash string to 80-byte padded bytes."""
    hash_bytes = hash_str.encode("utf-8")
    hash_bytes = hash_bytes.ljust(HASH_STR_SIZE, b"\0")
    return hash_bytes


def find_elf_file_offset(elf_path, gcc_prefix, symbol_vma):
    """Compute the ELF file offset for a symbol given its VMA.

    Searches through all PROGBITS sections to find which one contains
    the symbol, then computes: file_offset = (sym_vma - section_vma) + section_file_offset.
    """
    readelf = f"{gcc_prefix}-readelf"
    output = run_cmd([readelf, "-S", "-W", elf_path])
    for line in output.splitlines():
        m = re.match(
            r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)",
            line,
        )
        if m and m.group(2) == "PROGBITS":
            sec_vma = int(m.group(3), 16)
            sec_off = int(m.group(4), 16)
            sec_size = int(m.group(5), 16)
            if sec_vma <= symbol_vma < sec_vma + sec_size:
                file_offset = (symbol_vma - sec_vma) + sec_off
                logging.debug(
                    "Symbol VMA 0x%x in section %s (VMA 0x%x, offset 0x%x) → file offset 0x%x",
                    symbol_vma,
                    m.group(1),
                    sec_vma,
                    sec_off,
                    file_offset,
                )
                return file_offset
    return None


def main():
    ap = argparse.ArgumentParser(description="Insert SHA-256 hash of ICCM content into ROM ELF")
    ap.add_argument("input", help="Input ELF path (boot_rom.elf)")
    ap.add_argument(
        "--gcc-prefix",
        default="riscv64-unknown-elf",
        help="GCC toolchain prefix (default: riscv64-unknown-elf)",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true", help="Verify the hash embedded in the ELF")
    group.add_argument("-o", "--output", help="Output ELF path (may be same as input)")

    args = ap.parse_args()

    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="insert-rom-sha256: %(levelname)s: %(message)s")

    elf_path = args.input
    if not os.path.exists(elf_path):
        logging.error("File not found: %s", elf_path)
        return 1

    # Step 1: Find g_rom_sha256_str symbol in ELF.
    sym_vma = find_symbol_vma(elf_path, args.gcc_prefix, SYMBOL_NAME)
    if sym_vma is None:
        logging.error("Symbol '%s' not found in %s", SYMBOL_NAME, elf_path)
        return 1
    logging.debug("Symbol %s VMA: 0x%x", SYMBOL_NAME, sym_vma)

    # Step 2: Find the file offset for this symbol.
    file_offset = find_elf_file_offset(elf_path, args.gcc_prefix, sym_vma)
    if file_offset is None:
        logging.error("Could not find PROGBITS section containing symbol VMA 0x%x", sym_vma)
        return 1

    # Step 3: Extract ICCM binary and compute hash.
    with tempfile.TemporaryDirectory() as tmpdir:
        iccm_data = extract_iccm_binary(elf_path, args.gcc_prefix, tmpdir)

    if len(iccm_data) == 0:
        logging.error("ICCM binary extraction produced empty output")
        return 1

    hash_str = compute_hash(iccm_data)
    hash_bytes = format_hash_bytes(hash_str)

    if args.verify:
        # Read existing hash from ELF and compare.
        with open(elf_path, "rb") as f:
            elf_data = bytearray(f.read())
        existing = bytes(elf_data[file_offset : file_offset + HASH_STR_SIZE])
        if existing == hash_bytes:
            logging.debug("SHA256 digest matches!")
            return 0
        else:
            logging.error("SHA256 digest mismatch!")
            logging.error("Actual:   %s", existing)
            logging.error("Expected: %s", hash_bytes)
            return 1

    if args.output:
        # Patch the hash into the ELF.
        with open(elf_path, "rb") as f:
            elf_data = bytearray(f.read())

        if file_offset + HASH_STR_SIZE > len(elf_data):
            logging.error(
                "File too small: offset 0x%x + size %d > file size %d",
                file_offset,
                HASH_STR_SIZE,
                len(elf_data),
            )
            return 1

        elf_data[file_offset : file_offset + HASH_STR_SIZE] = hash_bytes

        with open(args.output, "wb") as f:
            f.write(elf_data)

        logging.info("Patched %s at offset 0x%x: %s", args.output, file_offset, hash_str)
    else:
        logging.info("ICCM hash: %s", hash_str)

    return 0


if __name__ == "__main__":
    sys.exit(main())
