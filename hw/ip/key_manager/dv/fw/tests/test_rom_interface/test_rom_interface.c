/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_interface.c
 * @brief ROM interface verification test
 *
 * Verifies ROM execution by calling functions at different addresses.
 * Tests ADD, XOR, and rotate operations via function calls to ensure
 * the CPU can correctly fetch and execute instructions from ROM.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_interface
 */

#include "test_common.h"

/* Test patterns */
#define TEST_INPUT 0xDEADBEEF
#define XOR_PATTERN 0x11111111
#define ADD_PATTERN 0x22222222
#define ROT_PATTERN 0x33333333

/* Forward declarations */
static uint32_t func_xor(uint32_t input);
static uint32_t func_add(uint32_t input);
static uint32_t func_rotate(uint32_t input);

/*
 * Test functions - noinline prevents inlining, ensuring actual
 * call/return sequences that exercise ROM fetches.
 */

__attribute__((noinline)) static uint32_t func_xor(uint32_t input) {
    return input ^ XOR_PATTERN;
}

__attribute__((noinline)) static uint32_t func_add(uint32_t input) {
    return input + ADD_PATTERN;
}

__attribute__((noinline)) static uint32_t func_rotate(uint32_t input) {
    /* Rotate and XOR to exercise more ROM fetches */
    uint32_t result = input;
    for (int i = 0; i < 4; i++) {
        result = (result << 8) | (result >> 24);
    }
    return result ^ ROT_PATTERN;
}

int main(void) {
    uint32_t result;
    uint32_t expected;

    TEST_INIT();

    TEST_LOG("Input value: 0x%08X", TEST_INPUT);

    /* Test 1: XOR function */
    TEST_SUBTEST_START("XOR function call");
    expected = TEST_INPUT ^ XOR_PATTERN;
    result = func_xor(TEST_INPUT);
    TEST_LOG("  Result:   0x%08X", result);
    TEST_LOG("  Expected: 0x%08X", expected);
    TEST_ASSERT_EQ(result, expected, "XOR result");
    TEST_SUBTEST_PASS();

    /* Test 2: ADD function */
    TEST_SUBTEST_START("ADD function call");
    expected = (TEST_INPUT + ADD_PATTERN) & 0xFFFFFFFF;
    result = func_add(TEST_INPUT);
    TEST_LOG("  Result:   0x%08X", result);
    TEST_LOG("  Expected: 0x%08X", expected);
    TEST_ASSERT_EQ(result, expected, "ADD result");
    TEST_SUBTEST_PASS();

    /* Test 3: Rotate function (4 full rotations = original, then XOR) */
    TEST_SUBTEST_START("Rotate function call");
    expected = TEST_INPUT ^ ROT_PATTERN;
    result = func_rotate(TEST_INPUT);
    TEST_LOG("  Result:   0x%08X", result);
    TEST_LOG("  Expected: 0x%08X", expected);
    TEST_ASSERT_EQ(result, expected, "ROT result");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
