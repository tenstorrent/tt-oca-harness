/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_kpv.c
 * @brief KPV driver unit test
 *
 * Exercises rom_kpv.h against actual KPV hardware in simulation:
 * - Scrambler init; shred with scrambler off, verify shred worked, then turn
 *   scrambler on and verify it is working; lock. Continue with rest.
 * - Shred-all, write/read key, write-lock, read-lock, shred-slot.
 * - Rejection of a word count that would spill out of a slot.
 *
 * Requires the DRBG to be initialized first (for the scrambler key).
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_kpv
 */

#include "test_common.h"
#include "rom_kpv.h"
#include "rom_drbg.h"
#include "rom_defs.h"

/**
 * Assert that not all words in the shredded region are the same constant.
 * Call after shred; reads KPV key words for slot range [slot_lo, slot_hi] (inclusive).
 */
static void verify_shred_result_varies(uint8_t slot_lo, uint8_t slot_hi) {
    uint32_t first = KPV_KEY_WORD(slot_lo, 0);
    uint8_t s, w;
    for (s = slot_lo; s <= slot_hi; s++) {
        for (w = (s == slot_lo) ? 1u : 0u; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
            if (KPV_KEY_WORD(s, w) != first) {
                return; /* at least two distinct values */
            }
        }
    }
    TEST_FAIL("shred result is constant (0x%08X) across slots %u..%u", (unsigned)first,
              (unsigned)slot_lo, (unsigned)slot_hi);
}

/** Write a known pattern to all KPV key words (scrambler must be off). */
static void write_known_pattern_all(void) {
    for (uint8_t s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
            KPV_KEY_WORD(s, w) = 0xDEAD0000u | (uint32_t)s << 8 | (uint32_t)w;
        }
    }
}

/** Capture all KPV key words; compare after shred and assert all changed. */
static void verify_shred_all_changed(void) {
    uint8_t s, w;

    write_known_pattern_all();
    rom_kpv_shred_all();
    for (s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        for (w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
            uint32_t expected = 0xDEAD0000u | (uint32_t)s << 8 | (uint32_t)w;
            uint32_t after = KPV_KEY_WORD(s, w);
            if (after == expected) {
                TEST_FAIL("shred_all: slot %u word %u unchanged (0x%08X)", (unsigned)s, (unsigned)w,
                          (unsigned)expected);
            }
        }
    }
    verify_shred_result_varies(0, (uint8_t)(ROM_KM_KPV_NUM_SLOTS - 1));
}

/** Capture one slot's key words; compare after shred_slot and assert all changed. */
static void verify_shred_slot_changed(uint8_t slot) {
    uint8_t w;
    const uint32_t pattern_base = 0xBEEF0000u | (uint32_t)slot << 8;

    for (w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        KPV_KEY_WORD(slot, w) = pattern_base | (uint32_t)w;
    }
    rom_kpv_shred_slot(slot);
    for (w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t expected = pattern_base | (uint32_t)w;
        uint32_t after = KPV_KEY_WORD(slot, w);
        if (after == expected) {
            TEST_FAIL("shred_slot(%u): word %u unchanged (0x%08X)", (unsigned)slot, (unsigned)w,
                      (unsigned)expected);
        }
    }
    verify_shred_result_varies(slot, slot);
}

/**
 * Verify scrambler stores all words of a slot in scrambled form.
 * Call with scrambler enabled. Writes distinct plaintext to each word, then
 * reads raw (scrambler off) and asserts every word differs from plaintext.
 */
static void verify_scrambler_slot(uint8_t slot) {
    uint8_t w;

    rom_kpv_scrambler_enable();
    for (w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t plain = 0xAAAAAAAAu + (uint32_t)w;
        KPV_KEY_WORD(slot, w) = plain;
    }
    rom_kpv_scrambler_disable();
    for (w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t plain = 0xAAAAAAAAu + (uint32_t)w;
        uint32_t stored = KPV_KEY_WORD(slot, w);
        if (stored == plain) {
            TEST_FAIL("scrambler: slot %u word %u stored as plaintext (0x%08X)", (unsigned)slot,
                      (unsigned)w, (unsigned)plain);
        }
    }
    rom_kpv_scrambler_enable();
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1500000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(123, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    rom_drbg_init();

    /* 1. Scrambler init (do not enable or lock yet) */
    TEST_SUBTEST_START("Scrambler init");
    rom_kpv_init_scrambler();
    TEST_LOG("  Scrambler initialized");
    TEST_SUBTEST_PASS();

    /* 2. Shred_all with scrambler off, verify all words changed, then verify scrambler works */
    TEST_SUBTEST_START("Shred_all and scrambler verify");
    {
        rom_kpv_scrambler_disable();
        verify_shred_all_changed();
        /* Turn scrambler on and verify all words in slot 0 are stored scrambled */
        verify_scrambler_slot(0);
        TEST_LOG("  shred_all and scrambler verified");
    }
    TEST_SUBTEST_PASS();

    /* 3. Shred_slot with scrambler off, verify all words in slot changed, then verify scrambler
     * works */
    TEST_SUBTEST_START("Shred_slot and scrambler verify");
    {
        const uint8_t slot = 2;

        rom_kpv_scrambler_disable();
        verify_shred_slot_changed(slot);
        /* Verify all words in slot are stored scrambled when scrambler is on */
        verify_scrambler_slot(slot);
        TEST_LOG("  shred_slot(%u) and scrambler verified", (unsigned)slot);
    }
    TEST_SUBTEST_PASS();

    /* 4. Lock scrambler and continue with rest of test */
    TEST_SUBTEST_START("Scrambler lock");
    rom_kpv_scrambler_lock();
    TEST_LOG("  Scrambler locked");
    TEST_SUBTEST_PASS();

    /* 5. Write key to slot 0 */
    TEST_SUBTEST_START("Write key to slot 0");
    {
        uint32_t key_in[16];
        uint32_t i;
        for (i = 0; i < 16; i++) {
            key_in[i] = 0x01020304u + i;
        }
        int rc = rom_kpv_write_slot(0, key_in, 16);
        if (rc != 0) {
            TEST_FAIL("write_slot slot 0 returned %d", rc);
        }
        TEST_LOG("  write_slot slot 0 ok");
    }
    TEST_SUBTEST_PASS();

    /* 6. Read key from slot 0 */
    TEST_SUBTEST_START("Read key from slot 0");
    {
        uint32_t key_out[16];
        uint32_t i;

        int rc = rom_kpv_read_slot(0, key_out, 16);
        if (rc != 0) {
            TEST_FAIL("read_slot slot 0 returned %d", rc);
        }
        for (i = 0; i < 16; i++) {
            uint32_t expected = 0x01020304u + i;
            TEST_ASSERT_EQ(key_out[i], expected, "key word");
        }
        TEST_LOG("  read_slot slot 0 matches");
    }
    TEST_SUBTEST_PASS();

    /* 7. Write-lock slot 0 */
    TEST_SUBTEST_START("Write-lock slot 0");
    {
        uint32_t new_key[16];
        uint32_t i;
        for (i = 0; i < 16; i++) {
            new_key[i] = 0xFFu;
        }
        rom_kpv_write_lock(0);
        int rc = rom_kpv_write_slot(0, new_key, 16);
        if (rc != -1) {
            TEST_FAIL("write_slot to write-locked slot should return -1, got %d", rc);
        }
        TEST_LOG("  write-lock verified");
    }
    TEST_SUBTEST_PASS();

    /* 8. Read-lock slot 0 */
    TEST_SUBTEST_START("Read-lock slot 0");
    {
        uint32_t key_out[16];

        rom_kpv_read_lock(0);
        int rc = rom_kpv_read_slot(0, key_out, 16);
        if (rc != -1) {
            TEST_FAIL("read_slot from read-locked slot should return -1, got %d", rc);
        }
        TEST_LOG("  read-lock verified");
    }
    TEST_SUBTEST_PASS();

    /* 9. Shred-slot: slot 1 (unlocked) wipes all words; slot 0 (write+read
     *    locked) wipes via the hardware erase path and clears its CTRL
     *    locks, leaving the slot reusable. */
    TEST_SUBTEST_START("Shred-slot");
    {
        if (!tb_drbg_set_seed(123, 1000)) {
            TEST_FAIL("tb_drbg_set_seed failed");
        }
        rom_drbg_init();
        verify_shred_slot_changed(1);

        rom_kpv_shred_slot(0);
        if (KPV_CTRL(0).f.lock_write || KPV_CTRL(0).f.lock_use) {
            TEST_FAIL("shred_slot(0) did not clear slot 0 CTRL locks (0x%08X)",
                      (unsigned)KPV_CTRL(0).w);
        }

        /* Slot 0 is now reusable: a fresh key write must succeed. */
        {
            uint32_t key_in[16];
            for (uint32_t i = 0; i < 16; i++) {
                key_in[i] = 0x11223300u + i;
            }
            int wrc = rom_kpv_write_slot(0, key_in, 16);
            if (wrc != 0) {
                TEST_FAIL("write_slot to shredded slot 0 returned %d", wrc);
            }
        }
        TEST_LOG("  shred-slot on locked slot verified");
    }
    TEST_SUBTEST_PASS();

    /* Slots are contiguous, so a word count past the end of one would spill
     * into the next; both primitives must reject it before touching the KPV. */
    TEST_SUBTEST_START("write_slot/read_slot reject an out-of-range word count");
    {
        uint32_t buf[ROM_KM_KPV_WORDS_PER_SLOT];
        for (uint32_t i = 0; i < ROM_KM_KPV_WORDS_PER_SLOT; i++) {
            buf[i] = 0xC0DE0000u + i;
        }

        if (rom_kpv_write_slot(0, buf, 0) != -1) {
            TEST_FAIL("write_slot with n_words=0 should return -1");
        }
        if (rom_kpv_write_slot(0, buf, (uint8_t)(ROM_KM_KPV_WORDS_PER_SLOT + 1)) != -1) {
            TEST_FAIL("write_slot with n_words=%u should return -1",
                      (unsigned)ROM_KM_KPV_WORDS_PER_SLOT + 1u);
        }
        if (rom_kpv_read_slot(0, buf, 0) != -1) {
            TEST_FAIL("read_slot with n_words=0 should return -1");
        }
        if (rom_kpv_read_slot(0, buf, (uint8_t)(ROM_KM_KPV_WORDS_PER_SLOT + 1)) != -1) {
            TEST_FAIL("read_slot with n_words=%u should return -1",
                      (unsigned)ROM_KM_KPV_WORDS_PER_SLOT + 1u);
        }

        /* The full-slot count remains legal. */
        if (rom_kpv_write_slot(0, buf, (uint8_t)ROM_KM_KPV_WORDS_PER_SLOT) != 0) {
            TEST_FAIL("write_slot with a full slot should succeed");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
