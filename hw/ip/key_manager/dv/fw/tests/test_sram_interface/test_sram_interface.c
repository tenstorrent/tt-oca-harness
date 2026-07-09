/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_sram_interface.c
 * @brief SRAM interface verification test
 *
 * Verifies SRAM read/write operations and code execution from SRAM:
 * 1. Basic write/read test
 * 2. Multi-word pattern test
 * 3. Byte-level access test
 * 4. Code execution from SRAM
 *
 * Run with:
 *   make run_fw FW_TEST=test_sram_interface
 */

#include "test_common.h"

/* Test memory regions in a mid/high SRAM scratch window away from linker-placed globals. */
#define TEST_DATA_BASE (SRAM_BASE + 0x2800)
#define SRAM_CODE_BASE (SRAM_BASE + 0x3000) /* Area for executable code */

/* Test patterns */
#define TEST_PATTERN_1 0xDEADBEEF
#define TEST_PATTERN_2 0xCAFEBABE
#define TEST_PATTERN_3 0xA5A5A5A5
#define ADD_CONSTANT 0x12345678

/* Forward declarations */
static uint32_t sram_add_function(uint32_t input);
static void sram_func_end_marker(void);

/*
 * Simple function to be copied to SRAM and executed.
 * Position-independent: only uses relative addressing.
 */
__attribute__((noinline)) static uint32_t sram_add_function(uint32_t input) {
    return input + ADD_CONSTANT;
}

/* End marker to calculate function size */
__attribute__((noinline)) static void sram_func_end_marker(void) {
    __asm__ volatile("");
}

/* Function pointer type */
typedef uint32_t (*add_func_t)(uint32_t);

int main(void) {
    TEST_INIT();

    /* Test 1: Basic SRAM write/read */
    TEST_SUBTEST_START("Basic write/read");
    {
        volatile uint32_t *addr = (volatile uint32_t *)TEST_DATA_BASE;
        *addr = TEST_PATTERN_1;
        uint32_t readback = *addr;
        TEST_LOG("  Wrote: 0x%08X", TEST_PATTERN_1);
        TEST_LOG("  Read:  0x%08X", readback);
        TEST_ASSERT_EQ(readback, TEST_PATTERN_1, "SRAM readback");
    }
    TEST_SUBTEST_PASS();

    /* Test 2: Multi-word pattern write/read */
    TEST_SUBTEST_START("Multi-word pattern");
    {
        volatile uint32_t *base = (volatile uint32_t *)(TEST_DATA_BASE + 0x100);
        base[0] = 0x11111111;
        base[1] = 0x22222222;
        base[2] = 0x33333333;
        base[3] = 0x44444444;

        TEST_LOG("  Pattern[0]: 0x%08X", base[0]);
        TEST_LOG("  Pattern[1]: 0x%08X", base[1]);
        TEST_LOG("  Pattern[2]: 0x%08X", base[2]);
        TEST_LOG("  Pattern[3]: 0x%08X", base[3]);

        TEST_ASSERT_EQ(base[0], 0x11111111, "pattern[0]");
        TEST_ASSERT_EQ(base[1], 0x22222222, "pattern[1]");
        TEST_ASSERT_EQ(base[2], 0x33333333, "pattern[2]");
        TEST_ASSERT_EQ(base[3], 0x44444444, "pattern[3]");
    }
    TEST_SUBTEST_PASS();

    /* Test 3: Byte-level access */
    TEST_SUBTEST_START("Byte-level access");
    {
        volatile uint8_t *byte_addr = (volatile uint8_t *)(TEST_DATA_BASE + 0x200);
        volatile uint32_t *word_addr = (volatile uint32_t *)(TEST_DATA_BASE + 0x200);

        /* Write individual bytes */
        byte_addr[0] = 0xA5;
        byte_addr[1] = 0xA5;
        byte_addr[2] = 0xA5;
        byte_addr[3] = 0xA5;

        /* Read back as word */
        uint32_t read_val = *word_addr;
        TEST_LOG("  Byte writes: 0xA5, 0xA5, 0xA5, 0xA5");
        TEST_LOG("  Word read:   0x%08X", read_val);
        TEST_ASSERT_EQ(read_val, TEST_PATTERN_3, "byte access");
    }
    TEST_SUBTEST_PASS();

    /* Test 4: Execute code from SRAM */
    TEST_SUBTEST_START("Code execution from SRAM");
    {
        /* Calculate function size.
         * Use byte granularity: function entry can be 16-bit aligned with C ISA. */
        uint32_t func_start = (uint32_t)sram_add_function;
        uint32_t func_end = (uint32_t)sram_func_end_marker;
        uint32_t func_size_bytes = func_end - func_start;

        TEST_LOG("  Copying function to SRAM (0x%08X)", SRAM_CODE_BASE);
        TEST_LOG("  Function size: %d bytes", func_size_bytes);

        /* Copy function to SRAM (byte-wise to avoid misaligned source loads). */
        volatile uint8_t *src = (volatile uint8_t *)func_start;
        volatile uint8_t *dst = (volatile uint8_t *)SRAM_CODE_BASE;
        for (uint32_t i = 0; i < func_size_bytes; i++) {
            dst[i] = src[i];
        }

        /* Memory barrier */
        __asm__ volatile("fence" ::: "memory");

        /* Execute from SRAM */
        add_func_t sram_func = (add_func_t)SRAM_CODE_BASE;
        uint32_t input = TEST_PATTERN_1;
        uint32_t result = sram_func(input);
        uint32_t expected = input + ADD_CONSTANT;

        TEST_LOG("  Input:    0x%08X", input);
        TEST_LOG("  Result:   0x%08X", result);
        TEST_LOG("  Expected: 0x%08X", expected);
        TEST_ASSERT_EQ(result, expected, "SRAM code execution");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
