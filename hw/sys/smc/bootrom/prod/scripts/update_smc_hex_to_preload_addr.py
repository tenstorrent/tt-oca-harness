# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse
import re


# Main script
def main():
    # Create the parser
    parser = argparse.ArgumentParser(description=get_description())

    # Add arguments
    parser.add_argument("in_file", help="Path to the *.hex file")
    parser.add_argument("--out_file", help="New *.hex file name")
    parser.add_argument("--start_addr", help="Address offset to be replaced", default="0")

    # Parse the arguments
    args = parser.parse_args()

    out_file = ""
    if args.out_file is None:
        out_file = args.in_file  # Re-write the input file
    else:
        out_file = args.out_file  # Write a new file

    start_addr_int = 0
    if is_hex(args.start_addr):
        start_addr_int = int(args.start_addr, 16)
    else:
        start_addr_int = int(args.start_addr)

    replace_offsets_in_hex_file(args.in_file, out_file, start_addr_int)


def get_description():
    description = """This script adjusts the addresses in the SMC embedded FW test *.hex from the
    'System Address' to physical address for preloading into the SRAM.  This is due to the
    *.hex generation flow which uses the 'System Address'
    """
    return description


# replace_offsets_in_hex_file
#   Assumes the input file is a hex file and needs to update the address offsets
def replace_offsets_in_hex_file(in_file, out_file, start_addr):
    # Open the file and read its contents
    with open(in_file, "r") as file:
        lines = file.readlines()

    # Create a pattern to match strings that start with "@" followed by hex digits
    pattern = re.compile(r"@([0-9A-Fa-f]+)")

    # Initially unset and will be set on the first
    # appearance of an address.  The first address
    # is assumed to be the 'start address' of the file
    # and therefore all other addresses will be offset
    # from the this 'start address'
    addr_offset = None

    # Process each line
    new_lines = []
    for line in lines:
        # Search for the pattern in the current line
        match = pattern.search(line)
        if match:
            # Extract the hexadecimal number (as a string)
            hex_string = match.group(1)

            # Convert the hexadecimal string to an integer
            hex_number = int(hex_string, 16)

            # If the addr_offset is not yet set, then
            # will assume the first address encounter is
            # the original base address and
            if addr_offset is None:
                addr_offset = hex_number - start_addr

            # Apply new offset
            updated_number = hex_number - addr_offset
            if updated_number < 0:
                raise RuntimeError(
                    f"Attempted to apply offset: {addr_offset} to address: {hex_string} which results in a negative address"
                )

            # Replace the original hex number in the line with the new one
            updated_hex_string = f"@{updated_number:X}"  # Format as uppercase hex

            # Replace the matched part of the line with the new value
            line = pattern.sub(updated_hex_string, line)

        # Add the (possibly modified) line to the new_lines list
        new_lines.append(line)

    # Write the modified contents back to the file
    with open(out_file, "w") as file:
        file.writelines(new_lines)

    print(f"File {out_file} processed and modified.")


def is_hex(s):
    if s.startswith("0x") or s.startswith("0X"):
        try:
            int(s, 16)
            return True
        except ValueError:
            return False
    return False


# Ensure that the main function is called after definitions
if __name__ == "__main__":
    main()
