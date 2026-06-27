/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>

// Define constants for initialization and interrupt done values
#define get_seed              0x12345678
#define sram_start            0xdeadbeef
#define sram_doublebit        0x56127834
#define sram_int_done         0xfadedc0d
#define dcache_1bit_start     0xeadbeef1
#define dcache_2bit_start     0xeadbeef2
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

  struct metal_buserror * local_buserrorunit = (struct metal_buserror *) priv_data;
  
  // Confirm that a load/store error caused this interrupt
  metal_buserror_event_t cause = metal_buserror_get_cause(local_buserrorunit); 
  if (cause == METAL_BUSERROR_EVENT_DATA_CORRECTABLE_ECC_ERROR) {
      write_scratch(0, dcache_singlebit_done); // to sync with coco_tb
      serviced_single_bit_interrupt = true;
  } else if (cause == METAL_BUSERROR_EVENT_DATA_UNCORRECTABLE_ECC_ERROR) {
      write_scratch(0, dcache_doublebit_done); // to sync with coco_tb
      serviced_double_bit_interrupt = true;
  } else if (cause == METAL_BUSERROR_EVENT_LOAD_STORE_ERROR) {
      // write correct value to memory and write to scratch to indicate interrupt done
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

uint8_t generate_ecc_bits_for_64bit_data(uint64_t data_input) {
    uint8_t check_bits[7];

    // Masks derived from the _coded_syndromeUInt_T* wires in the SV module
    const uint64_t MASK_CB0 = 0xAB55555556AAAD5BULL; // Corresponds to ^_coded_syndromeUInt_T
    const uint64_t MASK_CB1 = 0xCD9999999B33366DULL; // Corresponds to ^_coded_syndromeUInt_T_3
    const uint64_t MASK_CB2 = 0xF1E1E1E1E3C3C78EULL; // Corresponds to ^_coded_syndromeUInt_T_6
    const uint64_t MASK_CB3 = 0x1FE01FE03FC07F0ULL;  // Corresponds to ^_coded_syndromeUInt_T_9
    const uint64_t MASK_CB4 = 0x1FFFE0003FFF800ULL; // Corresponds to ^_coded_syndromeUInt_T_12
    const uint64_t MASK_CB5 = 0x1FFFFFFFC000000ULL; // Corresponds to ^_coded_syndromeUInt_T_15
    const uint64_t MASK_CB6 = 0xFE00000000000000ULL; // Corresponds to ^_coded_syndromeUInt_T_18

    // Calculate the 7 individual check bits (cb0 to cb6)
    // The order corresponds to how they appear in the SV concatenation for ECC bits [70:64]
    check_bits[0] = calculate_parity_u64(data_input & MASK_CB0); // cb0
    check_bits[1] = calculate_parity_u64(data_input & MASK_CB1); // cb1
    check_bits[2] = calculate_parity_u64(data_input & MASK_CB2); // cb2
    check_bits[3] = calculate_parity_u64(data_input & MASK_CB3); // cb3
    check_bits[4] = calculate_parity_u64(data_input & MASK_CB4); // cb4
    check_bits[5] = calculate_parity_u64(data_input & MASK_CB5); // cb5
    check_bits[6] = calculate_parity_u64(data_input & MASK_CB6); // cb6

    // Calculate the overall parity bit (P_overall), which is ECC bit 71
    int parity_of_data_input = calculate_parity_u64(data_input);
    uint8_t p_overall = check_bits[0] ^ check_bits[1] ^ check_bits[2] ^ \
                        check_bits[3] ^ check_bits[4] ^ check_bits[5] ^ \
                        check_bits[6] ^ parity_of_data_input;

    // Assemble the 8 ECC bits: P_overall, cb6, cb5, cb4, cb3, cb2, cb1, cb0
    uint8_t ecc_output = 0;
    ecc_output |= (p_overall & 1)   << 7; // Bit 71 (MSB of ECC byte)
    ecc_output |= (check_bits[6] & 1) << 6; // Bit 70
    ecc_output |= (check_bits[5] & 1) << 5; // Bit 69
    ecc_output |= (check_bits[4] & 1) << 4; // Bit 68
    ecc_output |= (check_bits[3] & 1) << 3; // Bit 67
    ecc_output |= (check_bits[2] & 1) << 2; // Bit 66
    ecc_output |= (check_bits[1] & 1) << 1; // Bit 65
    ecc_output |= (check_bits[0] & 1) << 0; // Bit 64 (LSB of ECC byte)

    return ecc_output;
}