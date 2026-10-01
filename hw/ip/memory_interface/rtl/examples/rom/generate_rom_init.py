#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
ROM Initialization File Generator

This script generates a VMEM format initialization file for the ROM wrapper.
It fills the ROM with various patterns including:
- Known test patterns at the beginning
- Random values for the majority of the ROM
- Special values and markers

Usage:
    python3 generate_rom_init.py [output_file] [--entries N] [--width W] [--seed S]

Arguments:
    output_file: Output VMEM file (default: example_rom_init.vmem)
    --entries N: Number of ROM entries (default: 1024)
    --width W: Data width in bits (default: 32)
    --seed S: Random seed for reproducible output (default: 42)
"""

import argparse
import random
import sys
from datetime import datetime


def generate_rom_init(output_file, num_entries=1024, data_width=32, seed=42):
    """Generate ROM initialization file with mixed patterns"""

    # Set random seed for reproducible output
    random.seed(seed)

    # Calculate max value for the given width
    max_val = (1 << data_width) - 1
    hex_width = (data_width + 3) // 4  # Number of hex digits needed

    print(f"Generating ROM init file: {output_file}")
    print(f"  Entries: {num_entries}")
    print(f"  Width: {data_width} bits")
    print(f"  Hex digits per entry: {hex_width}")
    print(f"  Random seed: {seed}")

    with open(output_file, "w") as f:
        # Write header
        f.write("// ROM Initialization File - Auto-generated\n")
        f.write(f"// Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("// Format: VMEM (Verilog Memory format)\n")
        f.write(f"// Data Width: {data_width} bits\n")
        f.write(f"// Entries: {num_entries} (0x000 to 0x{num_entries - 1:03X})\n")
        f.write("// Random seed: {}\n".format(seed))
        f.write("//\n")

        # Section 1: Known test patterns (first 64 entries)
        f.write("// Address 0x000-0x03F: Known test patterns and boot vectors\n")

        # Boot/reset vectors
        test_patterns = [
            0xDEADBEEF,
            0x12345678,
            0xABCDEF00,
            0xFEEDFACE,
            0xCAFEBABE,
            0xBAADF00D,
            0xDEADC0DE,
            0xFACADE00,
            0xBEEFCAFE,
            0xC0FFEE00,
            0xDEFEC8ED,
            0xFACEB00C,
            0xBADCAB1E,
            0xBEADFEED,
            0xCAFEFACE,
            0xDEADFEED,
        ]

        # Power-of-2 patterns
        power_patterns = [1 << i for i in range(16)]

        # Alternating patterns
        alt_patterns = [
            0xAAAAAAAA & max_val,
            0x55555555 & max_val,
            0xCCCCCCCC & max_val,
            0x33333333 & max_val,
            0xF0F0F0F0 & max_val,
            0x0F0F0F0F & max_val,
            0xFF00FF00 & max_val,
            0x00FF00FF & max_val,
            0xFFFF0000 & max_val,
            0x0000FFFF & max_val,
            0xFFFFFFFF & max_val,
            0x00000000,
            0x12345678,
            0x87654321,
            0xFEDCBA98,
            0x89ABCDEF,
        ]

        # Version/ID information
        version_info = [
            0x20250101,  # Version: 2025.01.01
            0x54540001,  # TT ID: TT0001
            0x524F4D00,  # ROM identifier: "ROM\0"
            0x45584D50,  # Example: "EXMP"
            0x56312E30,  # Version: "V1.0"
            0x20323032,  # Year: " 202"
            0x35303930,  # Date: "5090"
            0x31323A30,  # Time: "12:0"
            0x30303030,  # Padding: "0000"
            0xFFFFFFFF,  # End marker
            0xFFFFFFFF,  # End marker
            0xFFFFFFFF,  # End marker
            0xFFFFFFFF,  # End marker
            0xFFFFFFFF,  # End marker
            0xFFFFFFFF,  # End marker
            0xFFFFFFFF,  # End marker
        ]

        # Combine all known patterns
        known_patterns = test_patterns + power_patterns + alt_patterns + version_info

        # Write known patterns (first 64 entries)
        for i, pattern in enumerate(known_patterns[:64]):
            masked_pattern = pattern & max_val
            f.write(f"{masked_pattern:0{hex_width}X}\n")

        # Section 2: Sequential counter (next 64 entries)
        f.write("// Address 0x040-0x07F: Sequential counter values\n")
        for i in range(64):
            f.write(f"{i:0{hex_width}X}\n")

        # Section 3: Random values (remaining entries)
        remaining_entries = num_entries - 128
        f.write(f"// Address 0x080-0x{num_entries - 1:03X}: Random values\n")

        # Generate random values in chunks for better performance
        chunk_size = 100
        for chunk_start in range(0, remaining_entries, chunk_size):
            chunk_end = min(chunk_start + chunk_size, remaining_entries)
            random_values = [random.randint(0, max_val) for _ in range(chunk_end - chunk_start)]

            for val in random_values:
                f.write(f"{val:0{hex_width}X}\n")

        # Add some special markers at the very end if there's space
        if num_entries >= 1020:
            # Overwrite last few entries with special end markers
            f.seek(f.tell() - (4 * (hex_width + 1)))  # Go back 4 entries
            f.write(f"{'DEADBEEF'[:hex_width]:0>{hex_width}}\n")
            f.write(f"{'CAFEBABE'[:hex_width]:0>{hex_width}}\n")
            f.write(f"{'BAADF00D'[:hex_width]:0>{hex_width}}\n")
            f.write(f"{'FFFFFFFF'[:hex_width]:0>{hex_width}}\n")

    print(f"Successfully generated {output_file} with {num_entries} entries")


def main():
    parser = argparse.ArgumentParser(
        description="Generate ROM initialization file with test patterns and random data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "output_file",
        nargs="?",
        default="example_rom_init.vmem",
        help="Output VMEM file (default: example_rom_init.vmem)",
    )

    parser.add_argument(
        "--entries", "-n", type=int, default=1024, help="Number of ROM entries (default: 1024)"
    )

    parser.add_argument(
        "--width", "-w", type=int, default=32, help="Data width in bits (default: 32)"
    )

    parser.add_argument(
        "--seed",
        "-s",
        type=int,
        default=42,
        help="Random seed for reproducible output (default: 42)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.entries <= 0:
        print("Error: Number of entries must be positive", file=sys.stderr)
        sys.exit(1)

    if args.width <= 0 or args.width > 64:
        print("Error: Data width must be between 1 and 64 bits", file=sys.stderr)
        sys.exit(1)

    try:
        generate_rom_init(args.output_file, args.entries, args.width, args.seed)
    except Exception as e:
        print(f"Error generating ROM init file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
