/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_erase.c
 * @brief KPV per-slot hardware erase test (issue #3193)
 *
 * Exercises the per-slot CTRL.erase control and rom_kpv_erase_slot():
 * - Erase overwrites all key words of a slot even when the slot is
 *   write-locked and read-locked (erase is not blocked by the locks).
 * - Erase clears the slot CTRL register (lock_write, lock_use, erase, extend,
 *   last_dword), so the slot becomes reusable.
 * - A multi-slot (extended) key is erased across all its slots.
 *
 * Requires the DRBG to be initialized first (for the scrambler key).
 *
 * Run with:
 *   make run_fw FW_TEST=test_kpv_erase
 */

#include "test_common.h"
#include "rom_kpv.h"
#include "rom_drbg.h"
#include "rom_defs.h"

/** Write a distinct known pattern to all 16 words of a slot. */
static void write_pattern_slot(uint8_t slot) {
    for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++)
        KPV_KEY_WORD(slot, w) = 0xC0DE0000u | (uint32_t)slot << 8 | (uint32_t)w;
}

/** Assert that every word of a slot differs from the known pattern. */
static void verify_slot_changed(uint8_t slot) {
    for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t expected = 0xC0DE0000u | (uint32_t)slot << 8 | (uint32_t)w;
        uint32_t after = KPV_KEY_WORD(slot, w);
        if (after == expected) {
            TEST_FAIL("erase: slot %u word %u unchanged (0x%08X)", (unsigned)slot, (unsigned)w,
                      (unsigned)expected);
        }
    }
}

/** Assert that the slot CTRL register is fully cleared after erase. */
static void verify_ctrl_cleared(uint8_t slot) {
    km_kpv__ctrl_reg_t ctrl;
    ctrl.w = KPV_CTRL(slot).w;
    if (ctrl.w != 0u) {
        TEST_FAIL("erase: slot %u CTRL not cleared (0x%08X)", (unsigned)slot, (unsigned)ctrl.w);
    }
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

    /* Keep the scrambler disabled so raw stored data can be inspected. */
    rom_kpv_init_scrambler();
    rom_kpv_scrambler_disable();

    /* 1. Erase a single locked slot: data wiped, locks cleared, slot reusable. */
    TEST_SUBTEST_START("Erase locked single slot");
    {
        const uint8_t slot = 5;
        uint32_t key_in[16];
        for (uint32_t i = 0; i < 16; i++) key_in[i] = 0x11223300u + i;

        if (rom_kpv_write_key(slot, key_in, 16) != 0) {
            TEST_FAIL("write_key slot %u failed", (unsigned)slot);
        }

        /* Lock the slot for read and write; erase must bypass both. */
        rom_kpv_write_lock(slot);
        rom_kpv_read_lock(slot);
        if (!KPV_CTRL(slot).f.lock_write || !KPV_CTRL(slot).f.lock_use) {
            TEST_FAIL("slot %u locks not set before erase", (unsigned)slot);
        }

        /* Overwrite raw storage with a known pattern so we can detect change. */
        write_pattern_slot(slot);

        rom_kpv_erase_slot(slot);

        verify_ctrl_cleared(slot);
        verify_slot_changed(slot);

        /* Slot must be reusable now that locks are cleared. */
        uint32_t key2[16];
        for (uint32_t i = 0; i < 16; i++) key2[i] = 0x44556600u + i;
        if (rom_kpv_write_key(slot, key2, 16) != 0) {
            TEST_FAIL("write_key to erased slot %u failed (not reusable)", (unsigned)slot);
        }

        uint32_t key_out[16];
        uint8_t key_len = 0;
        if (rom_kpv_read_key(slot, key_out, &key_len) != 0) {
            TEST_FAIL("read_key from reused slot %u failed", (unsigned)slot);
        }
        TEST_ASSERT_EQ(key_len, 16u, "reused key_len");
        for (uint32_t i = 0; i < 16; i++)
            TEST_ASSERT_EQ(key_out[i], 0x44556600u + i, "reused key word");

        TEST_LOG("  single-slot erase, clear, and reuse verified");
    }
    TEST_SUBTEST_PASS();

    /* 2. Erase a multi-slot (extended) key across all of its slots. */
    TEST_SUBTEST_START("Erase multi-slot key");
    {
        const uint8_t base = 10;
        const uint8_t klen = 20; /* 2 slots: EXTEND=1 */
        uint32_t key_in[20];
        for (uint32_t i = 0; i < klen; i++) key_in[i] = 0x77000000u + i;

        if (rom_kpv_write_key(base, key_in, klen) != 0) {
            TEST_FAIL("write_key multi-slot base %u failed", (unsigned)base);
        }
        rom_kpv_write_lock(base);
        rom_kpv_read_lock(base);

        write_pattern_slot(base);
        write_pattern_slot((uint8_t)(base + 1));

        rom_kpv_erase_slot(base);

        verify_ctrl_cleared(base);
        verify_ctrl_cleared((uint8_t)(base + 1));
        verify_slot_changed(base);
        verify_slot_changed((uint8_t)(base + 1));

        TEST_LOG("  multi-slot erase verified");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
