/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// SRAM Performance Test - Side-Effect vs Normal Mode
//
// Compares SRAM access performance between side-effect mode and normal mode
// by configuring the MRAC register and measuring clock cycles.
//
//-----------------------------------------------------------------------------

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "sep.h"
#include "sep_outbound_filter.h"

//-----------------------------------------------------------------------------
// Configuration
//-----------------------------------------------------------------------------

// MRAC register values
// Region 1 (0x10000000-0x1FFFFFFF) contains SRAM at 0x10100000
// Bits [3:2] control region 1: 01 = normal, 10 = side-effect
#define MRAC_NORMAL_MODE 0xAAAAAA64     // Region 1 = no side-effect (cacheable)
#define MRAC_SIDEEFFECT_MODE 0xAAAAAA68 // Region 1 = side-effect

// Test parameters - tuned for ~50k total operations
// 256 words × 50 iters × 2 patterns × 2 modes = 51,200 operations
#define NUM_WORDS 256     // Number of SRAM words to test (1KB)
#define NUM_ITERATIONS 50 // Number of test iterations

// Keep the test clear of the top of SRAM; SRAM lies outside the DTCM/stack
// region in link/modes/tcm.ld.
#define SRAM_SAFETY_MARGIN 0x4000 // 16KB safety buffer at end
#define SRAM_USABLE_SIZE (OCH_SEP_TOP_SEP_SRAM_SIZE - SRAM_SAFETY_MARGIN)
#define SRAM_WORD_MAX (SRAM_USABLE_SIZE / 4) // Max word offset in usable SRAM

// LFSR seed for reproducible random addresses
#define LFSR_SEED 0xACE1u

//-----------------------------------------------------------------------------
// Timing functions using mcycle CSR
//-----------------------------------------------------------------------------

static inline uint32_t read_mcycle_lo(void) {
    uint32_t val;
    __asm__ volatile("csrr %0, mcycle" : "=r"(val));
    return val;
}

static inline uint32_t read_mcycle_hi(void) {
    uint32_t val;
    __asm__ volatile("csrr %0, mcycleh" : "=r"(val));
    return val;
}

static inline uint64_t read_mcycle(void) {
    uint32_t lo, hi, hi2;
    // Read hi, lo, hi again to handle wraparound
    do {
        hi = read_mcycle_hi();
        lo = read_mcycle_lo();
        hi2 = read_mcycle_hi();
    } while (hi != hi2);
    return ((uint64_t)hi << 32) | lo;
}

//-----------------------------------------------------------------------------
// MRAC control
//-----------------------------------------------------------------------------

static inline void set_mrac(uint32_t val) {
    __asm__ volatile("csrw 0x7c0, %0\n"
                     "fence\n" // Required after MRAC change for load/store regions
                     :
                     : "r"(val)
                     : "memory");
}

//-----------------------------------------------------------------------------
// LFSR for pseudo-random address generation
//-----------------------------------------------------------------------------

static uint16_t lfsr_state = LFSR_SEED;

static void lfsr_reset(void) {
    lfsr_state = LFSR_SEED;
}

// 16-bit Galois LFSR with taps at 16, 14, 13, 11 (maximal period 65535)
static uint16_t lfsr_next(void) {
    uint16_t lsb = lfsr_state & 1;
    lfsr_state >>= 1;
    if (lsb) {
        lfsr_state ^= 0xB400; // Taps: 16, 14, 13, 11
    }
    return lfsr_state;
}

//-----------------------------------------------------------------------------
// Generate NUM_WORDS distinct word offsets spread across SRAM. A duplicate
// offset would make the sequential test fail on the overwrite.
//-----------------------------------------------------------------------------

static uint32_t random_offsets[NUM_WORDS];

static void generate_random_offsets(void) {
    // Fixed-stride offsets: each is exactly 'stride' words from the next, so none
    // collide, and the last stays within SRAM_WORD_MAX.
    uint32_t stride = SRAM_WORD_MAX / NUM_WORDS; // ~60 words apart
    uint32_t start_offset = 0;                   // Start from beginning of SRAM

    for (int i = 0; i < NUM_WORDS; i++) {
        random_offsets[i] = start_offset + (uint32_t)i * stride;
    }
}

//-----------------------------------------------------------------------------
// SRAM stress test patterns
//-----------------------------------------------------------------------------

static volatile uint32_t *sram = (volatile uint32_t *)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR;

// Sequential pattern: Write all locations, then read all back
static int test_sequential(void) {
    uint32_t pattern_base = 0xDEAD0000;
    int total_ops = NUM_ITERATIONS * NUM_WORDS;
    int last_progress = -1;

    printf("[");
    int op_count = 0;
    for (int iter = 0; iter < NUM_ITERATIONS; iter++) {

        // Write phase
        for (int i = 0; i < NUM_WORDS; i++) {
            uint32_t offset = random_offsets[i];
            uint32_t pattern = pattern_base ^ offset ^ iter;
            sram[offset] = pattern;

            // Progress every 0.1% (1/1000)
            int progress = (op_count * 1000) / total_ops;
            if (progress > last_progress) {
                printf(".");
                last_progress = progress;
            }
            op_count++;
        }

        // Read and verify phase
        for (int i = 0; i < NUM_WORDS; i++) {
            uint32_t offset = random_offsets[i];
            uint32_t expected = pattern_base ^ offset ^ iter;
            uint32_t actual = sram[offset];
            if (actual != expected) {
                printf("] FAILED\n");
                printf("ERROR: Sequential @ offset %u iter %d: expected 0x%08X, got 0x%08X\n",
                       offset, iter, expected, actual);
                return -1;
            }

            // Progress every 0.1% (1/1000)
            int progress = (op_count * 1000) / total_ops;
            if (progress > last_progress) {
                printf(".");
                last_progress = progress;
            }
            op_count++;
        }
    }
    printf("] ");
    return 0;
}

// Interleaved pattern: Write-read-verify each location immediately
static int test_interleaved(void) {
    uint32_t pattern_base = 0xBEEF0000;
    int total_ops = NUM_ITERATIONS * NUM_WORDS * 2; // write + read per word
    int last_progress = -1;
    int op_count = 0;

    printf("[");
    for (int iter = 0; iter < NUM_ITERATIONS; iter++) {
        for (int i = 0; i < NUM_WORDS; i++) {
            uint32_t offset = random_offsets[i];
            uint32_t pattern = pattern_base ^ offset ^ iter;

            // Write
            sram[offset] = pattern;
            op_count++;

            // Progress every 0.1% (1/1000)
            int progress = (op_count * 1000) / total_ops;
            if (progress > last_progress) {
                printf(".");
                last_progress = progress;
            }

            // Immediate read and verify
            uint32_t actual = sram[offset];
            op_count++;

            // Progress every 0.1% (1/1000)
            progress = (op_count * 1000) / total_ops;
            if (progress > last_progress) {
                printf(".");
                last_progress = progress;
            }

            if (actual != pattern) {
                printf("] FAILED\n");
                printf("ERROR: Interleaved @ offset %u iter %d: expected 0x%08X, got 0x%08X\n",
                       offset, iter, pattern, actual);
                return -1;
            }
        }
    }
    printf("] ");
    return 0;
}

//-----------------------------------------------------------------------------
// Main
//-----------------------------------------------------------------------------

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    uint64_t se_seq_cycles, se_int_cycles;
    uint64_t nm_seq_cycles, nm_int_cycles;
    uint64_t start, end;
    int failed = 0;

    printf("\n");
    printf("========================================\n");
    printf("    SRAM Performance Test\n");
    printf("    Side-Effect vs Normal Mode\n");
    printf("========================================\n");
    printf("SRAM Base: 0x%08X\n", OCH_SEP_TOP_SEP_SRAM_BASE_ADDR);
    printf("SRAM Size: %d bytes\n", OCH_SEP_TOP_SEP_SRAM_SIZE);
    printf("Usable Range: 0x%08X - 0x%08X (%d bytes)\n", OCH_SEP_TOP_SEP_SRAM_BASE_ADDR,
           OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + SRAM_USABLE_SIZE - 1, SRAM_USABLE_SIZE);
    printf("Test Size: %d bytes (%d random words)\n", NUM_WORDS * 4, NUM_WORDS);
    printf("Iterations: %d\n", NUM_ITERATIONS);
    printf("\n");

    // Generate random offsets (same for all tests)
    printf("Generating %d random SRAM offsets...\n", NUM_WORDS);
    generate_random_offsets();

    //-------------------------------------------------------------------------
    // Side-Effect Mode Tests
    //-------------------------------------------------------------------------
    printf("\n--- Side-Effect Mode Tests ---\n");
    printf("Setting MRAC to 0x%08X (side-effect)\n", MRAC_SIDEEFFECT_MODE);
    set_mrac(MRAC_SIDEEFFECT_MODE);

    // Sequential test
    printf("Sequential pattern... ");
    start = read_mcycle();
    if (test_sequential() != 0) {
        failed = 1;
        printf("FAILED\n");
    } else {
        end = read_mcycle();
        se_seq_cycles = end - start;
        printf("%llu cycles\n", (unsigned long long)se_seq_cycles);
    }

    // Interleaved test
    printf("Interleaved pattern... ");
    start = read_mcycle();
    if (test_interleaved() != 0) {
        failed = 1;
        printf("FAILED\n");
    } else {
        end = read_mcycle();
        se_int_cycles = end - start;
        printf("%llu cycles\n", (unsigned long long)se_int_cycles);
    }

    //-------------------------------------------------------------------------
    // Normal Mode Tests
    //-------------------------------------------------------------------------
    printf("\n--- Normal Mode Tests ---\n");
    printf("Setting MRAC to 0x%08X (normal)\n", MRAC_NORMAL_MODE);
    set_mrac(MRAC_NORMAL_MODE);

    // Sequential test
    printf("Sequential pattern... ");
    start = read_mcycle();
    if (test_sequential() != 0) {
        failed = 1;
        printf("FAILED\n");
    } else {
        end = read_mcycle();
        nm_seq_cycles = end - start;
        printf("%llu cycles\n", (unsigned long long)nm_seq_cycles);
    }

    // Interleaved test
    printf("Interleaved pattern... ");
    start = read_mcycle();
    if (test_interleaved() != 0) {
        failed = 1;
        printf("FAILED\n");
    } else {
        end = read_mcycle();
        nm_int_cycles = end - start;
        printf("%llu cycles\n", (unsigned long long)nm_int_cycles);
    }

    //-------------------------------------------------------------------------
    // Summary
    //-------------------------------------------------------------------------
    printf("\n========================================\n");
    printf("    Performance Summary\n");
    printf("========================================\n");

    if (!failed) {
        printf("                  Side-Effect      Normal          Ratio\n");

        // Calculate ratios using integer math (ratio * 100 for 2 decimal places)
        uint32_t seq_ratio_int = 0, seq_ratio_frac = 0;
        uint32_t int_ratio_int = 0, int_ratio_frac = 0;

        if (nm_seq_cycles > 0) {
            seq_ratio_int = (uint32_t)(se_seq_cycles / nm_seq_cycles);
            seq_ratio_frac = (uint32_t)((se_seq_cycles * 100 / nm_seq_cycles) % 100);
        }
        if (nm_int_cycles > 0) {
            int_ratio_int = (uint32_t)(se_int_cycles / nm_int_cycles);
            int_ratio_frac = (uint32_t)((se_int_cycles * 100 / nm_int_cycles) % 100);
        }

        printf("Sequential:       %-14llu  %-14llu  %u.%02ux\n", (unsigned long long)se_seq_cycles,
               (unsigned long long)nm_seq_cycles, seq_ratio_int, seq_ratio_frac);

        printf("Interleaved:      %-14llu  %-14llu  %u.%02ux\n", (unsigned long long)se_int_cycles,
               (unsigned long long)nm_int_cycles, int_ratio_int, int_ratio_frac);

        printf("\n*** TEST PASSED ***\n");
        test_pass(0);
    } else {
        printf("\n*** TEST FAILED ***\n");
        test_fail(1);
    }

    // Keep CPU alive after signaling completion
    while (1) {
        __asm__("wfi");
    }
}
