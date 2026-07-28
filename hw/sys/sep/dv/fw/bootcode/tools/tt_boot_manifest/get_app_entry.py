import subprocess
import re
import sys
import os
from .utils import *

def convert_bin_to_elf_path(bin_path):
    # Split the path into directory, base name, and extension
    dir_name, base_name = os.path.split(bin_path)
    file_name, ext = os.path.splitext(base_name)
    assert ext and ext.lower() == '.bin', f"Error: Input file {bin_path} must have a .bin extension."
    # Create the new path with .elf extension
    elf_file_name = file_name + '.elf'
    elf_path = os.path.join(dir_name, elf_file_name)
    return elf_path

def get_start_address(bin_file):
    elf_file = convert_bin_to_elf_path(bin_file)
    #print(f"Run llvm-objdump on {elf_file} to get the start address.")
    # Run the llvm-objdump command and capture the output
    try:
        result = subprocess.run(['llvm-objdump', '--all-headers', elf_file], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        assert False, f"Error running llvm-objdump: {e.stderr}"
    # Parse the output to find the start address
    output = result.stdout
    match = re.search(r'start address: (0x[0-9a-fA-F]+)', output)
    assert match, f"Start address not found in llvm-objdump output for {elf_file}."
    start_address = match.group(1)
    #print(f"Start address: {start_address}")
    return convert_to_int(start_address)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bin_file>")
        sys.exit(1)

    bin_file = sys.argv[1]
    start_address = get_start_address(bin_file)

    if start_address:
        print(f"Start address: {start_address}")
