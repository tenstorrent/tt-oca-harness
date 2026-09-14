/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_drbg.c
 * @brief DRBG driver unit test
 *
 * Exercises rom_drbg_init(), rom_drbg_get_word(), and rom_drbg_get_block()
 * through the rom_drbg.h firmware API.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_drbg
 */

#include "test_common.h"
#include "rom_drbg.h"

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(100000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(42, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /* 1. rom_drbg_init: verify DRBG becomes ready */
    TEST_SUBTEST_START("rom_drbg_init");
    rom_drbg_init();
    {
        uint32_t status = rom_drbg_status_read();
        if (status == 0u) {
            TEST_FAIL("DRBG status is 0 after init - DRBG_READY never set");
        }
    }
    TEST_LOG("  DRBG initialized, status=0x%08X", rom_drbg_status_read());
    TEST_SUBTEST_PASS();

    /* 2. rom_drbg_get_word: read 4 words, each must be non-zero */
    TEST_SUBTEST_START("rom_drbg_get_word x4");
    {
        uint32_t i;
        for (i = 0; i < 4; i++) {
            uint32_t w = rom_drbg_get_word();
            TEST_LOG("  word[%u] = 0x%08X", (unsigned)i, w);
            if (w == 0u) {
                TEST_FAIL("rom_drbg_get_word returned 0 on call %u", (unsigned)i);
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* 3. rom_drbg_get_block: read 8 words into a buffer, all non-zero and not all identical.
     * A consuming DATA read advances the sampler; a PREFETCH_DATA (peek) read returns the
     * same held sample, so the block must contain at least two distinct values. */
    TEST_SUBTEST_START("rom_drbg_get_block (8 words)");
    {
        uint32_t buf[8];
        uint32_t i;
        uint32_t all_same;
        for (i = 0; i < 8; i++) {
            buf[i] = 0;
        }
        rom_drbg_get_block(buf, 8);
        for (i = 0; i < 8; i++) {
            TEST_LOG("  block[%u] = 0x%08X", (unsigned)i, buf[i]);
            if (buf[i] == 0u) {
                TEST_FAIL("rom_drbg_get_block word %u is 0", (unsigned)i);
            }
        }
        all_same = 1u;
        for (i = 1; i < 8; i++) {
            if (buf[i] != buf[0]) {
                all_same = 0u;
                break;
            }
        }
        if (all_same) {
            TEST_FAIL("rom_drbg_get_block returned 8 identical words 0x%08X "
                      "(peek register read instead of consuming DATA)",
                      buf[0]);
        }
    }
    TEST_SUBTEST_PASS();

    /* 4. Prefetch toggle: rom_drbg_get_block internally enables/disables prefetch.
     * Apply the same distinctness oracle: 4 words from a varied DRBG stream must not
     * all be the same value. */
    TEST_SUBTEST_START("Prefetch toggle via rom_drbg_get_block");
    {
        uint32_t buf2[4];
        uint32_t i;
        uint32_t all_same;
        for (i = 0; i < 4; i++) {
            buf2[i] = 0;
        }
        rom_drbg_get_block(buf2, 4);
        for (i = 0; i < 4; i++) {
            TEST_LOG("  prefetch_block[%u] = 0x%08X", (unsigned)i, buf2[i]);
            if (buf2[i] == 0u) {
                TEST_FAIL("Prefetch rom_drbg_get_block word %u is 0", (unsigned)i);
            }
        }
        all_same = 1u;
        for (i = 1; i < 4; i++) {
            if (buf2[i] != buf2[0]) {
                all_same = 0u;
                break;
            }
        }
        if (all_same) {
            TEST_FAIL("rom_drbg_get_block (prefetch) returned 4 identical words 0x%08X "
                      "(peek register read instead of consuming DATA)",
                      buf2[0]);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
