/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_scrambler_lock.c
 * @brief KPV scrambler lock test
 *
 * Provision key, set enable, set lock. Verify further writes to key and enable
 * are ignored (read back unchanged). Also verify key data registers are
 * unchanged after lock and after writing to the scrambler key register.
 *
 * Run with: make run_fw FW_TEST=test_kpv_scrambler_lock
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define KPV_SCRAMBLER_KEY_REG \
    (*(volatile km_kpv__kpv_scrambler_key_reg_t *)KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR)
#define KPV_SCRAMBLER_CTRL_REG \
    (*(volatile km_kpv__kpv_scrambler_ctrl_reg_t *)KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR)
#define KPV_KEY_WORD_ADDR(slot, word) \
    (KEY_MANAGER_KPV_BASE_ADDR + (uint32_t)(slot)*KEY_MANAGER_KPV_KEY_ENTRY_SIZE + \
     (uint32_t)(word)*4u)
#define KPV_KEY_WORD_REG(slot, word) \
    (*(volatile km_kpv__key_word_reg_t *)KPV_KEY_WORD_ADDR(slot, word))
#define KPV_CTRL_ADDR(slot) (KEY_MANAGER_KPV_CTRL_BASE_ADDR(0) + (uint32_t)(slot)*4u)
#define KPV_CTRL_REG(slot) (*(volatile km_kpv__ctrl_reg_t *)KPV_CTRL_ADDR(slot))

int main(void) {
    TEST_INIT();
    if (!tb_set_timeout(30000)) TEST_FAIL("timeout");

    /* Set scrambler key and enable first (before any key data or lock) */
    KPV_SCRAMBLER_KEY_REG.w = 0x12345678u;
    KPV_SCRAMBLER_CTRL_REG.f.enable = 1u;
    if (KPV_SCRAMBLER_CTRL_REG.f.enable != 1u) {
        TEST_FAIL("Enable not set (ctrl=0x%08X)", (unsigned)KPV_SCRAMBLER_CTRL_REG.w);
    }

    /* Allow reads up to word 1 for the slot we use */
    const unsigned KEY_SLOT = 0u;
    const unsigned KEY_WORD = 1u;
    const uint32_t KEY_VAL = 0xCAFEBABEu;
    KPV_CTRL_REG(KEY_SLOT).f.last_dword = KEY_WORD;

    /* Write key data with scrambling enabled; read back and save for later check */
    KPV_KEY_WORD_REG(KEY_SLOT, KEY_WORD).w = KEY_VAL;
    uint32_t key_data_before_lock = KPV_KEY_WORD_REG(KEY_SLOT, KEY_WORD).w;
    if (key_data_before_lock != KEY_VAL) {
        TEST_FAIL("Key data write failed: expected 0x%08X, got 0x%08X", (unsigned)KEY_VAL,
                  (unsigned)key_data_before_lock);
    }

    /* Set LOCK (write-one-only) */
    KPV_SCRAMBLER_CTRL_REG.f.lock = 1u;
    if (KPV_SCRAMBLER_CTRL_REG.f.lock != 1u) {
        TEST_FAIL("Lock not set (ctrl=0x%08X)", (unsigned)KPV_SCRAMBLER_CTRL_REG.w);
    }

    /* After lock, read of scrambler key must return 0 (key hidden from software) */
    uint32_t key_read_after_lock = KPV_SCRAMBLER_KEY_REG.w;
    if (key_read_after_lock != 0u) {
        TEST_FAIL("Scrambler key read after lock must return 0 (got 0x%08X)", key_read_after_lock);
    }

    /* Attempt to change key: must be ignored; read still returns 0 */
    KPV_SCRAMBLER_KEY_REG.w = 0xDEADBEEFu;
    uint32_t key_after = KPV_SCRAMBLER_KEY_REG.w;
    if (key_after != 0u) {
        TEST_FAIL("Key read after lock must return 0 (write ignored; got 0x%08X)", key_after);
    }

    /* Key data must be unchanged after lock and after writing to the scrambler key register */
    uint32_t key_data_after = KPV_KEY_WORD_REG(KEY_SLOT, KEY_WORD).w;
    if (key_data_after != key_data_before_lock) {
        TEST_FAIL(
            "Key data[%u][%u] changed after lock+scrambler key write: before 0x%08X, after 0x%08X",
            (unsigned)KEY_SLOT, (unsigned)KEY_WORD, (unsigned)key_data_before_lock,
            (unsigned)key_data_after);
    }

    /* Attempt to clear enable: must be ignored (enable still set) */
    KPV_SCRAMBLER_CTRL_REG.f.enable = 0u;
    if (KPV_SCRAMBLER_CTRL_REG.f.enable != 1u) {
        TEST_FAIL("Enable should be locked: ctrl=0x%08X (enable still 1)",
                  (unsigned)KPV_SCRAMBLER_CTRL_REG.w);
    }

    TEST_PASS();
    return 0;
}
