/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_shuffle.c
 * @brief Fisher-Yates shuffle unit tests
 *
 * Verifies rom_shuffle_index() bounds, rom_shuffle_array() permutation
 * integrity, and bit-pool refill behaviour.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_shuffle
 */

#include "test_common.h"
#include "rom_shuffle.h"
#include "rom_prng.h"
#include "rom_drbg.h"

static rom_km_prng_state_t g_prng;
static rom_km_bitpool_t g_pool;

static void simple_sort(uint16_t *arr, uint16_t n) {
    for (uint16_t i = 0; i < n; i++) {
        for (uint16_t j = (uint16_t)(i + 1u); j < n; j++) {
            if (arr[j] < arr[i]) {
                uint16_t t = arr[i];
                arr[i] = arr[j];
                arr[j] = t;
            }
        }
    }
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(300000)) {
        TEST_FAIL("tb_set_timeout failed");
    }
    if (!tb_drbg_set_seed(99, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }
    rom_drbg_init();
    rom_prng_seed(&g_prng);
    rom_shuffle_init(&g_pool);

    /* ---- shuffle_index ---- */

    TEST_SUBTEST_START("shuffle_index bound=1 always 0");
    {
        for (uint32_t i = 0; i < 10; i++) {
            uint16_t idx = rom_shuffle_index(&g_pool, &g_prng, 1);
            TEST_ASSERT_EQ(idx, 0u, "bound=1");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("shuffle_index various bounds in range");
    {
        static const uint16_t bounds[] = {2, 3, 7, 8, 16, 32};
        for (uint32_t b = 0; b < 6; b++) {
            uint16_t bound = bounds[b];
            for (uint32_t t = 0; t < 10; t++) {
                uint16_t idx = rom_shuffle_index(&g_pool, &g_prng, bound);
                if (idx >= bound) {
                    TEST_FAIL("index %u >= bound %u", (unsigned)idx, (unsigned)bound);
                }
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* ---- shuffle_array ---- */

    TEST_SUBTEST_START("shuffle_array size=1 unchanged");
    {
        uint16_t arr[1] = {42};
        rom_shuffle_array(&g_pool, &g_prng, arr, 1);
        TEST_ASSERT_EQ(arr[0], 42u, "single element");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("shuffle_array size=8 permutation");
    {
        uint16_t arr[8];
        for (uint8_t i = 0; i < 8; i++) arr[i] = (uint16_t)i;
        rom_shuffle_array(&g_pool, &g_prng, arr, 8);

        uint16_t sorted[8];
        for (uint8_t i = 0; i < 8; i++) sorted[i] = arr[i];
        simple_sort(sorted, 8);

        for (uint8_t i = 0; i < 8; i++) {
            TEST_ASSERT_EQ(sorted[i], i, "perm8 element");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("shuffle_array size=32 permutation");
    {
        uint16_t arr[32];
        for (uint8_t i = 0; i < 32; i++) arr[i] = (uint16_t)i;
        rom_shuffle_array(&g_pool, &g_prng, arr, 32);

        uint16_t sorted[32];
        for (uint8_t i = 0; i < 32; i++) sorted[i] = arr[i];
        simple_sort(sorted, 32);

        for (uint8_t i = 0; i < 32; i++) {
            TEST_ASSERT_EQ(sorted[i], i, "perm32 element");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("bit pool refill under heavy use");
    {
        for (uint32_t i = 0; i < 200; i++) {
            uint16_t idx = rom_shuffle_index(&g_pool, &g_prng, 17);
            if (idx >= 17) {
                TEST_FAIL("refill: index %u >= 17 at iter %u", (unsigned)idx, (unsigned)i);
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
