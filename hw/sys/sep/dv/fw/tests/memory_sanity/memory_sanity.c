/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//-----------------------------------------------------------------------------
// Memory Sanity Test
//
// Tests basic read/write operations to SRAM memory
//
//-----------------------------------------------------------------------------

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "sep.h"
#include "sep_outbound_filter.h"

// Test patterns
#define PATTERN_WALKING_1 0x00000001
#define PATTERN_WALKING_0 0xFFFFFFFE
#define PATTERN_CHECKERBOARD_A 0x55555555
#define PATTERN_CHECKERBOARD_B 0xAAAAAAAA
#define PATTERN_ALL_ONES 0xFFFFFFFF
#define PATTERN_ALL_ZEROS 0x00000000

// Number of 32-bit words to test (test first 1KB of SRAM)
#define TEST_WORDS 64
#define TEST_SPACING 64 // 64 bytes apart

static volatile uint32_t *sram = (volatile uint32_t *)SEP_TOP_SEP_SRAM_BASE_ADDR;

static int test_count = 0;
static int pass_count = 0;
static int fail_count = 0;

//-----------------------------------------------------------------------------
// Helper functions
//-----------------------------------------------------------------------------

static void report_test(const char *name, int passed) {
    test_count++;
    if (passed) {
        pass_count++;
        printf("[PASS] %s\n", name);
    } else {
        fail_count++;
        printf("[FAIL] %s\n", name);
    }
}

//-----------------------------------------------------------------------------
// Test: Basic Write/Read
//-----------------------------------------------------------------------------
static int test_basic_write_read(void) {
    printf("\n--- Test: Basic Write/Read ---\n");

    uint32_t test_value = 0xDEADBEEF;
    uint32_t read_value;

    // Write to first word
    sram[0] = test_value;

    // Read back
    read_value = sram[0];

    if (read_value != test_value) {
        printf("  ERROR: Expected 0x%08X, got 0x%08X\n", test_value, read_value);
        return 0;
    }

    printf("  Wrote 0x%08X, read back 0x%08X\n", test_value, read_value);
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Address Uniqueness (write different values to different addresses)
//-----------------------------------------------------------------------------
static int test_address_uniqueness(void) {
    printf("\n--- Test: Address Uniqueness ---\n");

    // Write address-based pattern to each word
    for (uint32_t i = 0; i < TEST_WORDS; i++) {
        sram[i * TEST_SPACING] = i ^ 0xA5A5A5A5;
    }

    // Verify all values
    for (uint32_t i = 0; i < TEST_WORDS; i++) {
        uint32_t expected = i ^ 0xA5A5A5A5;
        uint32_t actual = sram[i * TEST_SPACING];
        if (actual != expected) {
            printf("  ERROR at word %u: Expected 0x%08X, got 0x%08X\n", i, expected, actual);
            return 0;
        }
    }

    printf("  Verified %d words with unique values\n", TEST_WORDS);
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Pattern Fill (fill memory with pattern, verify, repeat)
//-----------------------------------------------------------------------------
static int test_pattern_fill(uint32_t pattern, const char *pattern_name) {
    printf("\n--- Test: Pattern Fill (%s = 0x%08X) ---\n", pattern_name, pattern);

    // Fill with pattern
    for (uint32_t i = 0; i < TEST_WORDS; i++) {
        sram[i * TEST_SPACING] = pattern;
    }

    // Verify pattern
    for (uint32_t i = 0; i < TEST_WORDS; i++) {
        uint32_t actual = sram[i * TEST_SPACING];
        if (actual != pattern) {
            printf("  ERROR at word %u: Expected 0x%08X, got 0x%08X\n", i, pattern, actual);
            return 0;
        }
        printf("  Verified word %u: Expected 0x%08X, got 0x%08X\n", i, pattern, actual);
    }

    printf("  Verified %d words with pattern 0x%08X\n", TEST_WORDS, pattern);
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Walking Ones
//-----------------------------------------------------------------------------
static int test_walking_ones(void) {
    printf("\n--- Test: Walking Ones ---\n");

    uint32_t pattern = PATTERN_WALKING_1;

    for (int bit = 0; bit < 32; bit++) {
        // Write pattern to first word
        sram[0] = pattern;

        // Read back and verify
        uint32_t actual = sram[0];
        if (actual != pattern) {
            printf("  ERROR at bit %d: Expected 0x%08X, got 0x%08X\n", bit, pattern, actual);
            return 0;
        }

        // Shift the walking 1
        pattern <<= 1;
    }

    printf("  All 32 walking-one patterns verified\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: Walking Zeros
//-----------------------------------------------------------------------------
static int test_walking_zeros(void) {
    printf("\n--- Test: Walking Zeros ---\n");

    uint32_t pattern = PATTERN_WALKING_0;

    for (int bit = 0; bit < 32; bit++) {
        // Write pattern to first word
        sram[0] = pattern;

        // Read back and verify
        uint32_t actual = sram[0];
        if (actual != pattern) {
            printf("  ERROR at bit %d: Expected 0x%08X, got 0x%08X\n", bit, pattern, actual);
            return 0;
        }

        // Rotate the walking 0
        pattern = (pattern << 1) | 1;
    }

    printf("  All 32 walking-zero patterns verified\n");
    return 1;
}

//-----------------------------------------------------------------------------
// Test: 64-bit Aligned Access
//-----------------------------------------------------------------------------
static int test_64bit_access(void) {
    printf("\n--- Test: 64-bit Aligned Access ---\n");

    volatile uint64_t *sram64 = (volatile uint64_t *)SEP_TOP_SEP_SRAM_BASE_ADDR;
    uint64_t test_value = 0xDEADBEEFCAFEBABEULL;
    uint64_t read_value;

    // Write 64-bit value
    sram64[0] = test_value;

    // Read back
    read_value = sram64[0];

    if (read_value != test_value) {
        printf("  ERROR: Expected 0x%016llX, got 0x%016llX\n", (unsigned long long)test_value,
               (unsigned long long)read_value);
        return 0;
    }

    printf("  Wrote 0x%016llX, read back 0x%016llX\n", (unsigned long long)test_value,
           (unsigned long long)read_value);
    return 1;
}

//-----------------------------------------------------------------------------
// Main
//-----------------------------------------------------------------------------
int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("     SEP Memory Sanity Test\n");
    printf("========================================\n");
    printf("SRAM Base: 0x%08X\n", SEP_TOP_SEP_SRAM_BASE_ADDR);
    printf("SRAM Size: %d bytes\n", SEP_TOP_SEP_SRAM_SIZE);
    printf("Testing:   %d words (%d bytes)\n", TEST_WORDS, TEST_WORDS * 4);

    // Run tests
    report_test("Basic Write/Read", test_basic_write_read());
    report_test("Address Uniqueness", test_address_uniqueness());
    report_test("Pattern: All Zeros", test_pattern_fill(PATTERN_ALL_ZEROS, "All Zeros"));
    report_test("Pattern: All Ones", test_pattern_fill(PATTERN_ALL_ONES, "All Ones"));
    report_test("Pattern: Checkerboard A",
                test_pattern_fill(PATTERN_CHECKERBOARD_A, "Checkerboard A"));
    report_test("Pattern: Checkerboard B",
                test_pattern_fill(PATTERN_CHECKERBOARD_B, "Checkerboard B"));
    report_test("Walking Ones", test_walking_ones());
    report_test("Walking Zeros", test_walking_zeros());
    report_test("64-bit Access", test_64bit_access());

    // Print summary
    printf("\n========================================\n");
    printf("     Test Summary\n");
    printf("========================================\n");
    printf("Total:  %d tests\n", test_count);
    printf("Passed: %d\n", pass_count);
    /* Use "Failures:" (not "Failed:") so this count line does not match the
     * regression fail-detection regex, which flags the substring "Failed"
     * even in "Failed: 0". The real pass/fail signal is test_pass/test_fail. */
    printf("Failures: %d\n", fail_count);

    if (fail_count == 0) {
        printf("\n*** ALL TESTS PASSED ***\n");
        test_pass(0);
    } else {
        printf("\n*** SOME TESTS FAILED ***\n");
        test_fail(fail_count);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
