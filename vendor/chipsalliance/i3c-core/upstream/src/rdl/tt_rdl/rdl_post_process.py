# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import re
import sys


def validate_file_path(fname):
    """Validate that the file path is safe and within expected boundaries."""
    # Get the absolute path of the input file
    abs_path = os.path.abspath(os.path.realpath(fname))

    # Define the base directory - script is in data/registers, output files are in rtl/csr
    # Go up to i3ccore_wrap directory (data/registers -> data -> i3ccore_wrap)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_directory = os.path.dirname(os.path.dirname(script_dir))

    # Check that the file is within the i3ccore_wrap directory
    if not abs_path.startswith(base_directory):
        raise ValueError(f"File path {abs_path} is outside the allowed directory {base_directory}")

    # Check that the file has the expected .sv extension
    if not abs_path.endswith('.sv'):
        raise ValueError(f"File {abs_path} does not have the expected .sv extension")

    # Check that the file exists
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"File {abs_path} does not exist")

    return abs_path


def postprocess_sv(fname):

    # Open file
    rhandle = open(fname, "r+")
    mod_cnt = 0
    mod_lines = ""

    found_hard_reset = None
    declared_includes = False
    extra_includes = ["i3c_sva.svh"]

    # Line by line manipulation
    # Look for unpacked arrays (could be struct arrays or signal arrays)
    # Look for unpacked struct types
    # NOTE: Will not detect unpacked arrays where the array identifier
    #       and dimensions are on separate lines
    for line in rhandle:
        has_assign = re.search(r"\bassign\b", line)
        has_reg_strb = re.search(r"\bdecoded_reg_strb\b", line)
        has_unpacked = re.search(r"\[\d+\]", line)
        has_struct = re.search(r"\bstruct\b\s*(?:unpacked)?", line)
        has_packed_struct = re.search(r"\bstruct\b\s*packed", line)
        is_module = re.search(r"\bmodule\s*\w*\s*\($", line)
        is_endmodule = re.search(r"\bendmodule\b", line)
        has_reset = re.search(r"\bnegedge\b", line)
        # Check if line contains an assignment (procedural or continuous)
        # Look for pattern: identifier[index] = value (array indexing assignment)
        has_assignment = re.search(r"\w+\s*\[[\w\-:]+\]\s*=", line)
        if has_reset is not None and found_hard_reset is None:
            substring = re.search(r"negedge (\w+.\w+)", line)
            reset_name = substring.group(1)
            # Find the hard reset if it exists
            # hard_reset_b, error_reset_b and cptra_pwrgood are used interchangeably
            found_hard_reset = re.search(r"hard_reset|pwrgood|error_reset", reset_name)
        # Skip lines with logic assignments or references to signals; we
        # only want to scrub signal definitions for unpacked arrays
        if has_assign is not None or has_reg_strb is not None or has_assignment is not None:
            mod_lines += line
        elif has_struct is not None and not has_packed_struct:
            line = re.sub(r"(\bstruct\b)\s*(?:unpacked)?", r"\1 packed", line)
            mod_lines += line
            mod_cnt += 1
        elif has_unpacked is not None:
            while has_unpacked is not None:
                #               whitespace
                #               |    existing dimensions (packed)
                #               |    |              identifier
                #               |    |              |          unpacked dimensions (ignore this iteration)
                #               |___ |____________  |______    |_______    unpacked dimension to modify
                #               |   \|            \ |      \   |       \   |
                line = re.sub(
                    r"(\s*)(\[[\w-]+:0\])*(\s*\w+)\s*(\[\d+\])*\[(\d+)\]", r"\1[\5-1:0]\2\3\4", line
                )
                has_unpacked = re.search(r"\[\d+\]", line)
            mod_lines += line
            mod_cnt += 1
        elif is_endmodule is not None:
            mod_lines += "\n"
            mod_lines += "`I3C_ASSERT_KNOWN(ERR_HWIF_IN, hwif_in, clk, !" + reset_name + ")\n"
            mod_lines += "\n"
            mod_lines += line
        # Include caliptra asserts header
        elif not declared_includes and is_module is not None:
            for inc in extra_includes:
                mod_lines += f'`include "{inc}"\n'
            mod_lines += "\n"
            mod_lines += line
            declared_includes = True
        else:
            mod_lines += line
    # print(f"modified {mod_cnt} lines with unpacked arrays in {fname}")

    # Close file for reading, reopen to write modified contents
    rhandle.close()
    whandle = open(fname, "w")
    whandle.write(mod_lines)
    whandle.close()


if __name__ == "__main__":
    # Get filename to scrub from arguments
    if len(sys.argv) == 1:
        print(f"{os.path.basename(sys.argv[0])} requires an argument to specify target file!")
        sys.exit(1)

    try:
        # Validate and sanitize the input file path
        fname = validate_file_path(sys.argv[1])
        print(f"file name to modify is {fname}")

        # Convert Unpacked Arrays/structs to Packed
        postprocess_sv(fname)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
