#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Generic OTBN C File Generator

Generates C files containing OTBN memory arrays and expected CRC values for
every OTBN firmware test.

The CRC follows the OpenTitan LOAD_CHECKSUM algorithm (upstream OpenTitan
util/otbn_build.py get_app_checksum() and
hw/ip/otbn/dv/otbnsim/stepped.py on_step_crc()).

Outputs a single C file with:
- IMEM array (uint32_t otbn_<app>_imem[])
- DMEM array (uint32_t otbn_<app>_dmem[])
- Expected CRC values (OTBN_<APP>_EXPECTED_IMEM_CRC, etc.)
- Word counts for each memory section
"""

import argparse
import binascii
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

from elftools.elf.elffile import ELFFile, SymbolTableSection  # type: ignore
from shared.toolchain import find_tool  # type: ignore


def call_rv32_objcopy(args):
    """Call the 32-bit RISC-V objcopy - reused from OpenTitan infrastructure

    Resolved through OpenTitan's own find_tool so RV32_TOOL_OBJCOPY and
    TOOLCHAIN_PATH are honoured; a riscv32-unknown-elf-objcopy is not the only
    binutils that can read these ELFs, and the toolchain container ships the
    riscv64 build.
    """
    cmd = [find_tool("objcopy")] + args
    subprocess.run(cmd, check=True)


def get_otbn_syms(elf_path: str) -> List[Tuple[str, int]]:
    """Get externally-visible symbols from an ELF

    Symbols are returned as a list of tuples: (name, address). This
    discards locals and also anything in .scratchpad, since those addresses
    aren't bus-accessible.

    Copied from opentitan/util/otbn_build.py:get_otbn_syms()
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # First, run objcopy to discard local symbols and the .scratchpad
        # section. We also use --extract-symbol since we don't care about
        # anything but the symbol data anyway.
        syms_path = os.path.join(tmpdir, "syms.elf")
        call_rv32_objcopy(
            ["-O", "elf32-littleriscv", "--remove-section=.scratchpad", "--extract-symbol"]
            + [elf_path, syms_path]
        )

        # Load the file and use elftools to grab any symbol table
        with open(syms_path, "rb") as syms_fd:
            syms_file = ELFFile(syms_fd)
            symtab = syms_file.get_section_by_name(".symtab")
            if symtab is None or not isinstance(symtab, SymbolTableSection):
                # No symbol table found or we did find a section called
                # .symtab, but it isn't actually a symbol table (huh?!). Give
                # up.
                return []

            ret = []
            for sym in symtab.iter_symbols():
                if sym["st_info"]["bind"] != "STB_GLOBAL":
                    continue
                addr = sym["st_value"]
                assert isinstance(addr, int)
                ret.append((sym.name, addr))
            return ret


def calculate_otbn_crc(imem_data, dmem_data, imem_base_addr=0, dmem_base_addr=0):
    """
    Calculate OTBN LOAD_CHECKSUM CRC using OpenTitan algorithm.

    This replicates the exact calculation from opentitan/util/otbn_build.py
    and matches the OTBN hardware LOAD_CHECKSUM register.

    NOTE: If dmem_data is empty, we still include one zero word in the CRC
    calculation to match the C array generation which outputs {0x00000000}
    for empty DMEM.
    """
    checksum = 0

    # Process IMEM writes (imem_flag = 1)
    for i in range(0, len(imem_data), 4):
        word_bytes = imem_data[i : i + 4]
        if len(word_bytes) < 4:
            word_bytes += b"\x00" * (4 - len(word_bytes))

        word_value = struct.unpack("<I", word_bytes)[0]  # Little-endian
        word_addr = (imem_base_addr + i) // 4

        # Build 48-bit CRC item: {imem=1, addr[14:0], data[31:0]}
        crc_item = (1 << 47) | ((word_addr & 0x7FFF) << 32) | word_value
        item_bytes = crc_item.to_bytes(6, "little")
        checksum = binascii.crc32(item_bytes, checksum)

    # Process DMEM writes (imem_flag = 0)
    # Special case: if dmem_data is empty, include one zero word to match
    # the C array generation which outputs {0x00000000} for empty DMEM
    dmem_to_process = dmem_data if len(dmem_data) > 0 else b"\x00\x00\x00\x00"

    for i in range(0, len(dmem_to_process), 4):
        word_bytes = dmem_to_process[i : i + 4]
        if len(word_bytes) < 4:
            word_bytes += b"\x00" * (4 - len(word_bytes))

        word_value = struct.unpack("<I", word_bytes)[0]  # Little-endian
        word_addr = (dmem_base_addr + i) // 4

        # Build 48-bit CRC item: {imem=0, addr[14:0], data[31:0]}
        crc_item = (0 << 47) | ((word_addr & 0x7FFF) << 32) | word_value
        item_bytes = crc_item.to_bytes(6, "little")
        checksum = binascii.crc32(item_bytes, checksum)

    return checksum & 0xFFFFFFFF


def binary_to_c_array(bin_data, array_name):
    """Convert binary data to C uint32_t array definition"""
    if len(bin_data) == 0:
        return f"const uint32_t {array_name}[] = {{0x00000000}};\nconst size_t {array_name}_words = 1;\n\n"

    # Pad to 4-byte alignment
    data = bin_data
    while len(data) % 4 != 0:
        data += b"\x00"

    # Convert to 32-bit words (little-endian)
    words = []
    for i in range(0, len(data), 4):
        word = struct.unpack("<I", data[i : i + 4])[0]
        words.append(f"0x{word:08x}")

    # Format as C array
    array_decl = f"const uint32_t {array_name}[] = {{\n"
    for i, word in enumerate(words):
        if i % 8 == 0:
            array_decl += "    "
        array_decl += f"{word}, "
        if i % 8 == 7:
            array_decl += "\n"

    if len(words) % 8 != 0:
        array_decl += "\n"

    array_decl += "};\n"
    array_decl += f"const size_t {array_name}_words = {len(words)};\n\n"

    return array_decl


def generate_c_file(app_name, imem_data, dmem_data, output_c, output_h, elf_path=None):
    """Generate C and header files with OTBN memory arrays, CRC values, and symbol addresses"""

    # Calculate CRC using OpenTitan algorithm
    expected_crc = calculate_otbn_crc(imem_data, dmem_data)

    # Extract symbol addresses if ELF file is provided
    # Tests derive their DMEM offsets from these symbols via OTBN_ADDR_T_INIT,
    # so a failed extraction must not degrade to a header of zero offsets: that
    # silently points every access at DMEM word 0 and the test still builds.
    symbols = []
    if elf_path and os.path.exists(elf_path):
        symbols = get_otbn_syms(elf_path)
        print(f"Extracted {len(symbols)} symbols from ELF")
        for name, addr in symbols:
            print(f"  {name}: 0x{addr:x}")

    # Generate array names
    imem_array_name = f"otbn_{app_name}_imem"
    dmem_array_name = f"otbn_{app_name}_dmem"
    crc_constant_name = f"OTBN_{app_name.upper()}_EXPECTED_CRC"

    # Generate OpenTitan-style symbol declarations and access macros
    symbol_declarations = ""
    if symbols:
        symbol_declarations = "\n/* OTBN symbol addresses (OpenTitan-style) */\n"

        # Declare symbols with OpenTitan prefix pattern
        for name, addr in symbols:
            symbol_name = f"_otbn_remote_app_{app_name}_{name}"
            symbol_declarations += f"#define {symbol_name} ((const uint32_t*)0x{addr:x})\n"

        # Add OpenTitan-compatible macros
        symbol_declarations += f"\n/* OpenTitan-compatible macros for {app_name} */\n"
        symbol_declarations += (
            "#define OTBN_DECLARE_SYMBOL_ADDR(app, sym) /* Already declared above */\n"
        )
        symbol_declarations += (
            "#define OTBN_ADDR_T_INIT(app, sym) ((uint32_t)_otbn_remote_app_##app##_##sym)\n"
        )

    # Generate header file (declarations only)
    header_content = f"""#ifndef OTBN_{app_name.upper()}_H
#define OTBN_{app_name.upper()}_H

#include <stdint.h>
#include <stddef.h>

/* Generated by common_otbn infrastructure using OpenTitan build tools */

/* Expected CRC checksum (matches OTBN LOAD_CHECKSUM register) */
#define {crc_constant_name} 0x{expected_crc:08x}U
{symbol_declarations}
/* OTBN memory arrays */
extern const uint32_t {imem_array_name}[];
extern const size_t {imem_array_name}_words;
extern const uint32_t {dmem_array_name}[];
extern const size_t {dmem_array_name}_words;

#endif // OTBN_{app_name.upper()}_H
"""

    # Generate source file (definitions)
    source_content = f"""/*
 * OTBN {app_name} Application Binary
 *
 * Generated by common_otbn infrastructure using:
 * - vendor/lowRISC/opentitan/upstream/hw/ip/otbn/util/otbn_as.py for assembly
 * - Static linker script (otbn_app.ld)
 * - OpenTitan CRC algorithm for validation
 * - Standard RISC-V objcopy for binary extraction
 * - Symbol address extraction from ELF
 */

#include "{app_name}_otbn.h"

/* IMEM: OTBN instruction memory */
{binary_to_c_array(imem_data, imem_array_name)}

/* DMEM: OTBN data memory initialization */
{binary_to_c_array(dmem_data, dmem_array_name)}"""

    # Write files
    with open(output_h, "w") as f:
        f.write(header_content)

    with open(output_c, "w") as f:
        f.write(source_content)

    # Print summary
    imem_words = len(imem_data) // 4 if len(imem_data) > 0 else 0
    dmem_words = len(dmem_data) // 4 if len(dmem_data) > 0 else 0

    print(f"Generated OTBN C files for '{app_name}':")
    print(f"  IMEM: {imem_words} words ({len(imem_data)} bytes)")
    print(f"  DMEM: {dmem_words} words ({len(dmem_data)} bytes)")
    print(f"  Expected CRC: 0x{expected_crc:08x}")
    print(f"  Output: {output_c}, {output_h}")


def main():
    parser = argparse.ArgumentParser(description="Generate C files for OTBN applications")
    parser.add_argument("--app-name", required=True, help="OTBN application name")
    parser.add_argument("--imem-bin", required=True, help="IMEM binary file")
    parser.add_argument("--dmem-bin", required=True, help="DMEM binary file")
    parser.add_argument("--output-c", required=True, help="Output C file")
    parser.add_argument("--output-h", required=True, help="Output header file")
    parser.add_argument("--elf-file", help="ELF file for symbol extraction (optional)")

    args = parser.parse_args()

    # Read binary data
    imem_data = Path(args.imem_bin).read_bytes() if Path(args.imem_bin).exists() else b""
    dmem_data = Path(args.dmem_bin).read_bytes() if Path(args.dmem_bin).exists() else b""

    # Generate C files
    generate_c_file(
        args.app_name, imem_data, dmem_data, args.output_c, args.output_h, args.elf_file
    )


if __name__ == "__main__":
    main()
