/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_scrambling.c
 * @brief KPV scrambler test
 *
 * 1. Set scrambler key, enable scrambling.
 * 2. Write values to all KPV key registers (32 slots x 16 words) and all CTRL
 *    registers; read back all key words and verify they match (round-trip with
 *    scrambling: write scramble -> store -> read descramble).
 * 3. Disable scrambling, read back all key words and confirm returned values
 *    are scrambled (i.e. not the original plaintext — raw stored form).
 *
 * Run with: make run_fw FW_TEST=test_kpv_scrambling
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define KPV_KEY_WORD_ADDR(slot, word) \
    (KEY_MANAGER_KPV_BASE_ADDR + (uint32_t)(slot)*KEY_MANAGER_KPV_KEY_ENTRY_SIZE + \
     (uint32_t)(word)*4u)
#define KPV_KEY_WORD_REG(slot, word) \
    (*(volatile km_kpv__key_word_reg_t *)KPV_KEY_WORD_ADDR(slot, word))

#define KPV_CTRL_ADDR(slot) (KEY_MANAGER_KPV_CTRL_BASE_ADDR(0) + (uint32_t)(slot)*4u)
#define KPV_CTRL_REG(slot) (*(volatile km_kpv__ctrl_reg_t *)KPV_CTRL_ADDR(slot))

#define KPV_SCRAMBLER_KEY_REG \
    (*(volatile km_kpv__kpv_scrambler_key_reg_t *)KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR)
#define KPV_SCRAMBLER_CTRL_REG \
    (*(volatile km_kpv__kpv_scrambler_ctrl_reg_t *)KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR)

#define NUM_SLOTS 32u
#define WORDS_PER_SLOT 16u

static inline void kpv_scrambler_set_key(uint32_t key) {
    KPV_SCRAMBLER_KEY_REG.w = key;
}

static inline void kpv_scrambler_enable(int enable) {
    KPV_SCRAMBLER_CTRL_REG.f.enable = (enable ? 1u : 0u);
}

/* Unique plaintext per (slot, word) for verification */
static inline uint32_t key_plaintext(uint32_t slot, uint32_t word) {
    return 0x11111111u + (slot * 0x10000u) + (word * 0x100u);
}

int main(void) {
    TEST_INIT();
    if (!tb_set_timeout(120000)) TEST_FAIL("timeout");

    kpv_scrambler_set_key(0xDEADBEEFu);
    kpv_scrambler_enable(1);

    /* Write all KPV key words and all CTRL registers with scrambling enabled */
    for (uint32_t s = 0; s < NUM_SLOTS; s++) {
        for (uint32_t w = 0; w < WORDS_PER_SLOT; w++)
            KPV_KEY_WORD_REG(s, w).w = key_plaintext(s, w);
        KPV_CTRL_REG(s).f.last_dword = 15u;
    }

    /* Verify scrambler and all CTRL registers before round-trip (ensure we get unscrambled
     * readback) */
    if (KPV_SCRAMBLER_KEY_REG.w != 0xDEADBEEFu)
        TEST_FAIL("Scrambler key before readback: expected 0xDEADBEEF, got 0x%08X",
                  (unsigned)KPV_SCRAMBLER_KEY_REG.w);
    if (KPV_SCRAMBLER_CTRL_REG.f.enable != 1u)
        TEST_FAIL("Scrambler enable before readback: expected 1, got %u",
                  (unsigned)KPV_SCRAMBLER_CTRL_REG.f.enable);
    for (uint32_t s = 0; s < NUM_SLOTS; s++) {
        if (KPV_CTRL_REG(s).f.last_dword != 15u)
            TEST_FAIL("CTRL[%u].last_dword before readback: expected 15, got %u", (unsigned)s,
                      (unsigned)KPV_CTRL_REG(s).f.last_dword);
        if (KPV_CTRL_REG(s).f.lock_write != 0u)
            TEST_FAIL("CTRL[%u].lock_write before readback: expected 0, got %u", (unsigned)s,
                      (unsigned)KPV_CTRL_REG(s).f.lock_write);
        if (KPV_CTRL_REG(s).f.lock_use != 0u)
            TEST_FAIL("CTRL[%u].lock_use before readback: expected 0, got %u", (unsigned)s,
                      (unsigned)KPV_CTRL_REG(s).f.lock_use);
    }

    /* Read back all key words with scrambling enabled; must match plaintext (unscrambled
     * round-trip) */
    for (uint32_t s = 0; s < NUM_SLOTS; s++) {
        for (uint32_t w = 0; w < WORDS_PER_SLOT; w++) {
            uint32_t expected = key_plaintext(s, w);
            uint32_t r = KPV_KEY_WORD_REG(s, w).w;
            if (r != expected) {
                TEST_FAIL("Round-trip slot %u word %u: expected 0x%08X, got 0x%08X", (unsigned)s,
                          (unsigned)w, expected, r);
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* Disable scrambling; read back all key words and confirm values are scrambled (not plaintext)
     */
    kpv_scrambler_enable(0);
    for (uint32_t s = 0; s < NUM_SLOTS; s++) {
        for (uint32_t w = 0; w < WORDS_PER_SLOT; w++) {
            uint32_t plain = key_plaintext(s, w);
            uint32_t r = KPV_KEY_WORD_REG(s, w).w;
            if (r == plain) {
                TEST_FAIL("Scrambled read slot %u word %u: got plaintext 0x%08X (expected stored "
                          "scrambled)",
                          (unsigned)s, (unsigned)w, plain);
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
