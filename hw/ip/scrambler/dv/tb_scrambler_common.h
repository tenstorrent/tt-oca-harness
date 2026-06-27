/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

//-----------------------------------------------------------------------------
// Common Verilator Testbench Template for SRAM Scrambler
//
// Provides run_word_tests() and run_bytewise_tests() template functions
// that work with any Verilator-generated DUT class.
//
// The scrambler is purely combinational:
//   - drive addr_i + write_data_i, call eval() -> read scrambled outputs
//   - store in C++ memory array, then set scrambled_read_data_i, eval() again
//
// Copyright 2026 Tenstorrent Inc.
//-----------------------------------------------------------------------------

#ifndef TB_SCRAMBLER_COMMON_H
#define TB_SCRAMBLER_COMMON_H

#include <cstdint>
#include <cstdio>
#include <vector>

// 32-bit LCG for reproducible pseudo-random data
static uint32_t lcg_state = 0;

static inline void lcg_seed(uint32_t seed) { lcg_state = seed; }
static inline uint32_t lcg_rand() {
    lcg_state = lcg_state * 1664525u + 1013904223u;
    return lcg_state;
}

//-----------------------------------------------------------------------------
// run_word_tests — BYTE_WISE=0 round-trip verification
//   Phase 1: write all addresses ascending (random data), read back ascending
//   Phase 2: write all addresses descending (sequential), read back descending
//-----------------------------------------------------------------------------
template<class DUT>
int run_word_tests(DUT& dut, int mem_depth, const char* name) {
    static const uint32_t KEY = 0xDEADBEEFu;
    std::vector<uint32_t> memory(mem_depth, 0);
    std::vector<uint32_t> expected(mem_depth, 0);
    int total_errors = 0;
    int errors;

    dut.scrambler_key_i = KEY;
    dut.byte_mask_i     = 0xF;

    printf("========================================\n");
    printf("Scrambler %s  BYTE_WISE=0 Tests\n", name);
    printf("Key: 0x%08X\n", KEY);
    printf("========================================\n");

    // --- Phase 1: ascending write, ascending read ---
    printf("\n--- Phase 1: Ascending ---\n");
    lcg_seed(42);
    for (int i = 0; i < mem_depth; i++) {
        dut.addr_i       = static_cast<uint16_t>(i);
        dut.write_data_i = lcg_rand();
        dut.eval();
        expected[i] = dut.write_data_i;
        memory[dut.scrambled_addr_o] = dut.scrambled_write_data_o;
        if (i < 10)
            printf("Write[%3d]: addr=0x%03X->0x%03X  data=0x%08X->0x%08X\n",
                   i, static_cast<unsigned>(dut.addr_i),
                   static_cast<unsigned>(dut.scrambled_addr_o),
                   expected[i],
                   static_cast<unsigned>(dut.scrambled_write_data_o));
    }
    errors = 0;
    for (int i = 0; i < mem_depth; i++) {
        dut.addr_i = static_cast<uint16_t>(i);
        dut.eval();
        dut.scrambled_read_data_i = memory[dut.scrambled_addr_o];
        dut.eval();
        uint32_t got = dut.read_data_o;
        if (got != expected[i]) {
            errors++;
            if (errors <= 10)
                printf("ERROR addr %d: expected 0x%08X  got 0x%08X\n",
                       i, expected[i], got);
        }
        if (i < 10)
            printf("Read[%3d]:  addr=0x%03X  out=0x%08X  exp=0x%08X  %s\n",
                   i, static_cast<unsigned>(dut.addr_i),
                   got, expected[i],
                   (got == expected[i]) ? "PASS" : "FAIL");
    }
    total_errors += errors;
    printf("Phase 1 errors: %d/%d\n", errors, mem_depth);
    printf(errors == 0 ? "*** PHASE 1 PASSED ***\n" : "*** PHASE 1 FAILED ***\n");

    // --- Phase 2: descending write, descending read ---
    printf("\n--- Phase 2: Descending ---\n");
    for (int i = mem_depth - 1; i >= 0; i--) {
        dut.addr_i       = static_cast<uint16_t>(i);
        dut.write_data_i = static_cast<uint32_t>(mem_depth - 1 - i);
        dut.eval();
        expected[i] = dut.write_data_i;
        memory[dut.scrambled_addr_o] = dut.scrambled_write_data_o;
    }
    errors = 0;
    for (int i = mem_depth - 1; i >= 0; i--) {
        dut.addr_i = static_cast<uint16_t>(i);
        dut.eval();
        dut.scrambled_read_data_i = memory[dut.scrambled_addr_o];
        dut.eval();
        uint32_t got = dut.read_data_o;
        if (got != expected[i]) {
            errors++;
            if (errors <= 10)
                printf("ERROR addr %d: expected 0x%08X  got 0x%08X\n",
                       i, expected[i], got);
        }
    }
    total_errors += errors;
    printf("Phase 2 errors: %d/%d\n", errors, mem_depth);
    printf(errors == 0 ? "*** PHASE 2 PASSED ***\n" : "*** PHASE 2 FAILED ***\n");

    printf("\n========================================\n");
    printf("All Tests Complete - %s  BYTE_WISE=0\n", name);
    printf("Total Errors: %d/%d\n", total_errors, mem_depth * 2);
    printf(total_errors == 0 ? "*** ALL TESTS PASSED ***\n"
                             : "*** TESTS FAILED ***\n");
    printf("========================================\n");
    return total_errors;
}

//-----------------------------------------------------------------------------
// run_bytewise_tests — BYTE_WISE=1 round-trip verification
//   Phase 1: write ascending (random data, full mask), read back ascending
//   Phase 2: write descending (sequential, full mask), read back descending
//-----------------------------------------------------------------------------
template<class DUT>
int run_bytewise_tests(DUT& dut, int mem_depth, const char* name) {
    static const uint32_t KEY = 0xDEADBEEFu;
    std::vector<uint32_t> memory(mem_depth, 0);
    std::vector<uint32_t> expected(mem_depth, 0);
    int total_errors = 0;
    int errors;

    dut.scrambler_key_i = KEY;
    dut.byte_mask_i     = 0xF;

    printf("========================================\n");
    printf("Scrambler %s  BYTE_WISE=1 Tests\n", name);
    printf("Key: 0x%08X\n", KEY);
    printf("========================================\n");

    // --- Phase 1: ascending write (random), ascending read ---
    printf("\n--- Phase 1: Full mask (0xF), ascending ---\n");
    lcg_seed(42);
    for (int i = 0; i < mem_depth; i++) {
        dut.addr_i       = static_cast<uint16_t>(i);
        dut.write_data_i = lcg_rand();
        dut.eval();
        expected[i] = dut.write_data_i;
        memory[dut.scrambled_addr_o] = dut.scrambled_write_data_o;
        if (i < 10)
            printf("Write[%3d]: addr=0x%03X->0x%03X  data=0x%08X->0x%08X\n",
                   i, static_cast<unsigned>(dut.addr_i),
                   static_cast<unsigned>(dut.scrambled_addr_o),
                   expected[i],
                   static_cast<unsigned>(dut.scrambled_write_data_o));
    }
    errors = 0;
    for (int i = 0; i < mem_depth; i++) {
        dut.addr_i = static_cast<uint16_t>(i);
        dut.eval();
        dut.scrambled_read_data_i = memory[dut.scrambled_addr_o];
        dut.eval();
        uint32_t got = dut.read_data_o;
        if (got != expected[i]) {
            errors++;
            if (errors <= 10)
                printf("ERROR addr %d: expected 0x%08X  got 0x%08X\n",
                       i, expected[i], got);
        }
        if (i < 10)
            printf("Read[%3d]:  addr=0x%03X  out=0x%08X  exp=0x%08X  %s\n",
                   i, static_cast<unsigned>(dut.addr_i),
                   got, expected[i],
                   (got == expected[i]) ? "PASS" : "FAIL");
    }
    total_errors += errors;
    printf("Phase 1 errors: %d/%d\n", errors, mem_depth);
    printf(errors == 0 ? "*** PHASE 1 PASSED ***\n" : "*** PHASE 1 FAILED ***\n");

    // --- Phase 2: descending write (sequential), descending read ---
    printf("\n--- Phase 2: Full mask (0xF), descending ---\n");
    for (int i = mem_depth - 1; i >= 0; i--) {
        dut.addr_i       = static_cast<uint16_t>(i);
        dut.write_data_i = static_cast<uint32_t>(i);
        dut.eval();
        expected[i] = dut.write_data_i;
        memory[dut.scrambled_addr_o] = dut.scrambled_write_data_o;
    }
    errors = 0;
    for (int i = mem_depth - 1; i >= 0; i--) {
        dut.addr_i = static_cast<uint16_t>(i);
        dut.eval();
        dut.scrambled_read_data_i = memory[dut.scrambled_addr_o];
        dut.eval();
        uint32_t got = dut.read_data_o;
        if (got != expected[i]) {
            errors++;
            if (errors <= 10)
                printf("ERROR addr %d: expected 0x%08X  got 0x%08X\n",
                       i, expected[i], got);
        }
    }
    total_errors += errors;
    printf("Phase 2 errors: %d/%d\n", errors, mem_depth);
    printf(errors == 0 ? "*** PHASE 2 PASSED ***\n" : "*** PHASE 2 FAILED ***\n");

    printf("\n========================================\n");
    printf("All Tests Complete - %s  BYTE_WISE=1\n", name);
    printf("Total Errors: %d/%d\n", total_errors, mem_depth * 2);
    printf(total_errors == 0 ? "*** ALL TESTS PASSED ***\n"
                             : "*** TESTS FAILED ***\n");
    printf("========================================\n");
    return total_errors;
}

#endif // TB_SCRAMBLER_COMMON_H
