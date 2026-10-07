/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

// Scratch-register handshake values exchanged with the testbench.
#define get_seed 0x12345678
#define sram_start 0xdeadbeef
#define sram_doublebit 0x56127834
#define sram_int_done 0xfadedc0d
#define dcache_1bit_start 0xeadbeef1
#define dcache_2bit_start 0xeadbeef2
#define dcache_singlebit_done 0xfaccfacc
#define dcache_doublebit_done 0xfaccdadd

// Flags and Extern vars for IRH
extern uint32_t spm_addr;
extern uint64_t true_mem_val;
extern volatile bool serviced_sram_error;
extern volatile bool serviced_single_bit_interrupt;
extern volatile bool serviced_double_bit_interrupt;

// Interrupt Handler
void beu_interrupt_handler(int id, void *priv_data) {

    struct metal_buserror *local_buserrorunit = (struct metal_buserror *)priv_data;

    metal_buserror_event_t cause = metal_buserror_get_cause(local_buserrorunit);
    if (cause == METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR) {
        write_scratch(0, dcache_singlebit_done); // to sync with coco_tb
        serviced_single_bit_interrupt = true;
    } else if (cause == METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR) {
        write_scratch(0, dcache_doublebit_done); // to sync with coco_tb
        serviced_double_bit_interrupt = true;
    } else if (cause == METAL_BUSERROR_EVENT_LOAD_STORE_ERROR) {
        write_scratch(0, sram_int_done); // to sync with coco_tb
        serviced_sram_error = true;
    } else {
        test_fail(0);
    }

    // cause register is for information only, clearing it doesn't clear the interrupt line
    if (metal_buserror_clear_cause(local_buserrorunit) != 0) {
        test_fail(0);
    }
    // clear the interrupt line
    if (metal_buserror_clear_event_accrued(local_buserrorunit, METAL_BUSERROR_EVENT_ALL) != 0) {
        test_fail(0);
    }
}

// Helper function to calculate parity of a byte (0 for even, 1 for odd)
static int calculate_parity_byte(uint8_t n) {
    // Efficient parity calculation (Hamming weight modulo 2)
    n ^= n >> 4;
    n ^= n >> 2;
    n ^= n >> 1;
    return n & 1;
}

// Helper function to calculate parity of a 64-bit unsigned integer (0 for even, 1 for odd)
static int calculate_parity_u64(uint64_t n) {
    n ^= n >> 32;
    n ^= n >> 16;
    n ^= n >> 8;
    n ^= n >> 4;
    n ^= n >> 2;
    n ^= n >> 1;
    return n & 1;
}

/*
 * EXPECT-SOURCE: SiFive Rocket Chip Hsiao SECDED (72,64) parity-check matrix
 * for 64-bit data words (SiFive E2/E3 Core Complex Manual — ECC / Bus Error
 * Unit data encoding; open-source rocket-chip util/ECC Hsiao construction).
 * Rows are the published H-matrix over data[63:0]; overall parity is XOR of
 * all data bits and check bits cb0..cb6.
 *
 * The fixed-vector KAT (data -> ECC byte) below is computed from this matrix
 * definition and spot-checks the encoder.
 */
static const uint64_t ECC64_HSIAO_H_ROW[7] = {
    0xAB55555556AAAD5BULL, /* cb0 — H-matrix row 0 */
    0xCD9999999B33366DULL, /* cb1 — H-matrix row 1 */
    0xF1E1E1E1E3C3C78EULL, /* cb2 — H-matrix row 2 */
    0x01FE01FE03FC07F0ULL, /* cb3 — H-matrix row 3 */
    0x01FFFE0003FFF800ULL, /* cb4 — H-matrix row 4 */
    0x01FFFFFFFC000000ULL, /* cb5 — H-matrix row 5 */
    0xFE00000000000000ULL, /* cb6 — H-matrix row 6 */
};

typedef struct {
    uint64_t data;
    uint8_t ecc;
} ecc64_kat_entry_t;

/* EXPECT-SOURCE: fixed vectors from ECC64_HSIAO_H_ROW (SiFive Hsiao SECDED). */
static const ecc64_kat_entry_t ECC64_KAT[] = {
    {0x0000000000000000ULL, 0x00}, {0x0000000000000001ULL, 0x83}, {0xFFFFFFFFFFFFFFFFULL, 0xFF},
    {0x0123456789ABCDEFULL, 0x9C}, {0xA5A5A5A5A5A5A5A5ULL, 0xD1}, {0x55AA55AA55AA55AAULL, 0x56},
};

uint8_t generate_ecc_bits_for_64bit_data(uint64_t data_input) {
    uint8_t check_bits[7];
    static int kat_checked = 0;

    // Calculate the 7 individual check bits (cb0 to cb6)
    // Order matches ECC byte bits [6:0] (cb6..cb0) with P_overall in bit 7
    for (int i = 0; i < 7; i++) {
        check_bits[i] = (uint8_t)calculate_parity_u64(data_input & ECC64_HSIAO_H_ROW[i]);
    }

    // Overall parity bit (P_overall) — ECC bit 71 / MSB of the ECC byte
    int parity_of_data_input = calculate_parity_u64(data_input);
    uint8_t p_overall = check_bits[0] ^ check_bits[1] ^ check_bits[2] ^ check_bits[3] ^
                        check_bits[4] ^ check_bits[5] ^ check_bits[6] ^ parity_of_data_input;

    // Assemble the 8 ECC bits: P_overall, cb6, cb5, cb4, cb3, cb2, cb1, cb0
    uint8_t ecc_output = 0;
    ecc_output |= (p_overall & 1) << 7;     // Bit 71 (MSB of ECC byte)
    ecc_output |= (check_bits[6] & 1) << 6; // Bit 70
    ecc_output |= (check_bits[5] & 1) << 5; // Bit 69
    ecc_output |= (check_bits[4] & 1) << 4; // Bit 68
    ecc_output |= (check_bits[3] & 1) << 3; // Bit 67
    ecc_output |= (check_bits[2] & 1) << 2; // Bit 66
    ecc_output |= (check_bits[1] & 1) << 1; // Bit 65
    ecc_output |= (check_bits[0] & 1) << 0; // Bit 64 (LSB of ECC byte)

    // One-shot KAT self-check against the fixed-vector table
    if (!kat_checked) {
        kat_checked = 1;
        for (unsigned k = 0; k < sizeof(ECC64_KAT) / sizeof(ECC64_KAT[0]); k++) {
            if (generate_ecc_bits_for_64bit_data(ECC64_KAT[k].data) != ECC64_KAT[k].ecc) {
                test_fail(0);
            }
        }
    }

    return ecc_output;
}
