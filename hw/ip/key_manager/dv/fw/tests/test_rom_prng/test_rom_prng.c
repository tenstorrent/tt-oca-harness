/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_prng.c
 * @brief xoshiro128++ PRNG unit tests
 *
 * Verifies rom_prng_next() produces non-zero, non-repeating output
 * for known state, and that rom_prng_seed() escapes the all-zero
 * absorbing state.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_prng
 */

#include "test_common.h"
#include "rom_prng.h"
#include "rom_drbg.h"

int main(void) {
    TEST_INIT();

    if (!tb_drbg_set_seed(42, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    TEST_SUBTEST_START("PRNG known-state outputs non-zero and unique");
    {
        rom_km_prng_state_t st;
        st.s[0] = 1;
        st.s[1] = 2;
        st.s[2] = 3;
        st.s[3] = 4;

        uint32_t vals[8];
        uint32_t i, j;
        for (i = 0; i < 8; i++) {
            vals[i] = rom_prng_next(&st);
            TEST_ASSERT_NE(vals[i], 0u, "PRNG output non-zero");
        }
        for (i = 0; i < 8; i++) {
            for (j = i + 1; j < 8; j++) {
                if (vals[i] == vals[j]) {
                    TEST_FAIL("PRNG outputs[%u]==outputs[%u]==0x%08X", (unsigned)i, (unsigned)j,
                              vals[i]);
                }
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("PRNG seed escapes all-zero state");
    {
        rom_km_prng_state_t st;
        st.s[0] = 0;
        st.s[1] = 0;
        st.s[2] = 0;
        st.s[3] = 0;

        rom_prng_seed(&st);

        uint32_t any = st.s[0] | st.s[1] | st.s[2] | st.s[3];
        TEST_ASSERT_NE(any, 0u, "state non-zero after seed");
        TEST_LOG("  state: 0x%08X 0x%08X 0x%08X 0x%08X", st.s[0], st.s[1], st.s[2], st.s[3]);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("PRNG 16 successive values non-repeating");
    {
        rom_km_prng_state_t st;
        rom_prng_seed(&st);

        uint32_t prev = rom_prng_next(&st);
        for (uint32_t i = 1; i < 16; i++) {
            uint32_t cur = rom_prng_next(&st);
            if (cur == prev) {
                TEST_FAIL("consecutive repeat at i=%u val=0x%08X", (unsigned)i, cur);
            }
            prev = cur;
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
