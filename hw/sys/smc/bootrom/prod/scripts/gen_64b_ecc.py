# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import sys


def gen_ecc(data_in):
    # The word which ECC will be calculated
    word_in = data_in

    # Masks for generating EDC bits
    masks = [
        0b1010101101010101010101010101010101010110101010101010110101011011,
        0b1100110110011001100110011001100110011011001100110011011001101101,
        0b1111000111100001111000011110000111100011110000111100011110001110,
        0b0000000111111110000000011111111000000011111111000000011111110000,
        0b0000000111111111111111100000000000000011111111111111100000000000,
        0b0000000111111111111111111111111111111100000000000000000000000000,
        0b1111111000000000000000000000000000000000000000000000000000000000,
    ]

    # Generate EDC bits by XORing masked word bits
    edc_tmp = [0] * 8
    for i, mask in enumerate(masks):
        masked_bits = word_in & mask
        edc_tmp[i] = (
            bin(masked_bits).count("1") % 2
        )  # XOR operation by counting '1's and taking modulo 2

    # Calculate overall parity
    edc_tmp[7] = bin(int("".join(str(bit) for bit in edc_tmp), 2) << 64 | word_in).count("1") % 2

    # Convert the ecc list of booleans back to an integer
    ecc = edc_tmp[::-1]
    ecc_int = int("".join(str(int(bit)) for bit in ecc), 2)

    return ecc_int


def process_file(input_file_path, output_file_path):
    with open(input_file_path, "rb") as input_file, open(output_file_path, "w") as output_file:
        while True:
            # Read 32-bit (4 bytes) from the file
            word_bytes = input_file.read(8)
            if not word_bytes:
                break  # End of file

            # Convert bytes to integer
            word = int.from_bytes(word_bytes, byteorder="little", signed=False)

            # Generate ECC for the 64-bit word
            ecc = gen_ecc(word)

            prot_word = word | ecc << 64

            # Write the original word + 8 bit ECC to the output file. Don't omit leading zeros
            output_file.write(f"{prot_word:016X}\n")


# This script converts a binary file into a hex file with SECDED ECC that follows Rocketchips ECC formula
# Example usage of this can be found in firmware/Makefile on line 72
process_file(sys.argv[1], sys.argv[2])
