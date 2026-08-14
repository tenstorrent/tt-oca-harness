/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_last_dword.c
 * @brief KPV last_dword enforcement
 *
 * Reads at or within last_dword return key data; reads beyond last_dword
 * return 0. Covers multiple slots, boundaries, and changing last_dword.
 *
 * Run with: make run_fw FW_TEST=test_kpv_last_dword
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* KPV (KM port) register struct access (from km_kpv.h) */
#define KPV_KEY_WORD_ADDR(slot, word) \
    (KEY_MANAGER_KPV_BASE_ADDR + (uint32_t)(slot)*KEY_MANAGER_KPV_KEY_ENTRY_SIZE + \
     (uint32_t)(word)*4u)
#define KPV_KEY_WORD_REG(slot, word) \
    (*(volatile km_kpv__key_word_reg_t *)KPV_KEY_WORD_ADDR(slot, word))

#define KPV_CTRL_ADDR(slot) (KEY_MANAGER_KPV_CTRL_BASE_ADDR(0) + (uint32_t)(slot)*4u)
#define KPV_CTRL_REG(slot) (*(volatile km_kpv__ctrl_reg_t *)KPV_CTRL_ADDR(slot))

static void set_last_dword(unsigned int slot, uint32_t last_dword_val) {
    km_kpv__ctrl_reg_t c = {.w = KPV_CTRL_REG(slot).w};
    c.f.last_dword = last_dword_val & 0xFu;
    KPV_CTRL_REG(slot).w = c.w;
}

int main(void) {
    TEST_INIT();
    if (!tb_set_timeout(40000)) TEST_FAIL("timeout");

    /* -----------------------------------------------------------------------
     * 1. last_dword = 0: only word 0 valid; words 1..15 read as 0.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("last_dword=0: only word 0 valid");
    {
        const unsigned int slot = 0;
        KPV_KEY_WORD_REG(slot, 0).w = 0xA1B2C3D4u;
        KPV_KEY_WORD_REG(slot, 1).w = 0xDEADBEEFu; /* stored but masked on read */
        set_last_dword(slot, 0u);

        if (KPV_KEY_WORD_REG(slot, 0).w != 0xA1B2C3D4u)
            TEST_FAIL("Word 0 should read 0xA1B2C3D4 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 0).w);
        if (KPV_KEY_WORD_REG(slot, 1).w != 0u || KPV_KEY_WORD_REG(slot, 2).w != 0u)
            TEST_FAIL("Words beyond last_dword must return 0");
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 2. last_dword = 3: words 0..3 valid; words 4..15 read as 0.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("last_dword=3: words 0..3 valid");
    {
        const unsigned int slot = 0;
        const uint32_t key[4] = {0x11111111u, 0x22222222u, 0x33333333u, 0x44444444u};
        for (int w = 0; w < 4; w++) KPV_KEY_WORD_REG(slot, w).w = key[w];
        KPV_KEY_WORD_REG(slot, 4).w = 0x55555555u; /* beyond range, masked on read */
        set_last_dword(slot, 3u);

        for (int w = 0; w < 4; w++) {
            if (KPV_KEY_WORD_REG(slot, w).w != key[w])
                TEST_FAIL("Word %d should read 0x%08X (got 0x%08X)", w, (unsigned)key[w],
                          (unsigned)KPV_KEY_WORD_REG(slot, w).w);
        }
        if (KPV_KEY_WORD_REG(slot, 4).w != 0u || KPV_KEY_WORD_REG(slot, 5).w != 0u)
            TEST_FAIL("Words 4..5 beyond last_dword must return 0");
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 3. last_dword = 15: all words 0..15 valid; no masking.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("last_dword=15: all words valid");
    {
        const unsigned int slot = 0;
        KPV_KEY_WORD_REG(slot, 14).w = 0xE0E0E0E0u;
        KPV_KEY_WORD_REG(slot, 15).w = 0xF00DF00Du;
        set_last_dword(slot, 15u);

        if (KPV_KEY_WORD_REG(slot, 14).w != 0xE0E0E0E0u)
            TEST_FAIL("Word 14 should read 0xE0E0E0E0 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 14).w);
        if (KPV_KEY_WORD_REG(slot, 15).w != 0xF00DF00Du)
            TEST_FAIL("Word 15 should read 0xF00DF00D (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 15).w);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 4. Different slot: slot 1 last_dword=2; slot 0 (last_dword=15) unchanged.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("Slot 1 last_dword=2; slot 0 independent");
    {
        KPV_KEY_WORD_REG(1, 0).w = 0xBEEF0001u;
        KPV_KEY_WORD_REG(1, 1).w = 0xBEEF0002u;
        KPV_KEY_WORD_REG(1, 2).w = 0xBEEF0003u;
        KPV_KEY_WORD_REG(1, 3).w = 0xBEEF0004u;
        set_last_dword(1, 2u);

        if (KPV_KEY_WORD_REG(1, 2).w != 0xBEEF0003u)
            TEST_FAIL("Slot 1 word 2 should read 0xBEEF0003 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(1, 2).w);
        if (KPV_KEY_WORD_REG(1, 3).w != 0u)
            TEST_FAIL("Slot 1 word 3 beyond last_dword must return 0 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(1, 3).w);
        /* Slot 0 still has last_dword=15 from subtest 3 */
        if (KPV_KEY_WORD_REG(0, 15).w != 0xF00DF00Du)
            TEST_FAIL("Slot 0 word 15 unchanged (got 0x%08X)", (unsigned)KPV_KEY_WORD_REG(0, 15).w);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 5. Boundary: last_dword=5 → word 5 valid, word 6 returns 0.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("Boundary: last_dword=5, word 5 valid word 6 zero");
    {
        const unsigned int slot = 2;
        KPV_KEY_WORD_REG(slot, 5).w = 0x50505050u;
        KPV_KEY_WORD_REG(slot, 6).w = 0x60606060u;
        set_last_dword(slot, 5u);

        if (KPV_KEY_WORD_REG(slot, 5).w != 0x50505050u)
            TEST_FAIL("Word 5 (== last_dword) should read 0x50505050 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 5).w);
        if (KPV_KEY_WORD_REG(slot, 6).w != 0u)
            TEST_FAIL("Word 6 (> last_dword) must return 0 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 6).w);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 6. Change last_dword: shrink range and re-read; beyond range now returns 0.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("Shrink last_dword: previously valid word now reads 0");
    {
        const unsigned int slot = 3;
        KPV_KEY_WORD_REG(slot, 7).w = 0x70707070u;
        KPV_KEY_WORD_REG(slot, 8).w = 0x80808080u;
        set_last_dword(slot, 8u);

        if (KPV_KEY_WORD_REG(slot, 8).w != 0x80808080u)
            TEST_FAIL("Word 8 should read 0x80808080 when last_dword=8 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 8).w);

        set_last_dword(slot, 7u);

        if (KPV_KEY_WORD_REG(slot, 7).w != 0x70707070u)
            TEST_FAIL("Word 7 should still read 0x70707070 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 7).w);
        if (KPV_KEY_WORD_REG(slot, 8).w != 0u)
            TEST_FAIL("Word 8 beyond new last_dword=7 must return 0 (got 0x%08X)",
                      (unsigned)KPV_KEY_WORD_REG(slot, 8).w);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
