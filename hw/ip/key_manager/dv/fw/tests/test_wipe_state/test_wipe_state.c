/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_wipe_state.c
 * @brief Wipe state test
 *
 * Subtest 1: Fill KPV with unscrambled data, verify readback, trigger wipe,
 *            verify WIPE_STATE IRQ and all KPV/scrambler zero.
 * Subtest 2: Enable and lock scrambling, fill KPV (stored scrambled), verify
 *            readback (descrambled), trigger wipe, verify all zero.
 *
 * Run with: make run_fw FW_TEST=test_wipe_state
 */

#include "test_common.h"
#include "irq_common.h"
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

#define KPV_NUM_SLOTS 32u
#define KPV_WORDS_PER_SLOT 16u
#define KEY_PATTERN(s, w) (0xCA000000u | ((s) << 8) | (w))

static void fill_kpv_and_ctrl(void) {
    for (unsigned int s = 0; s < KPV_NUM_SLOTS; s++) {
        for (unsigned int w = 0; w < KPV_WORDS_PER_SLOT; w++) {
            KPV_KEY_WORD_REG(s, w).w = KEY_PATTERN(s, w);
        }
        KPV_CTRL_REG(s).f.last_dword = KPV_WORDS_PER_SLOT - 1u;
        KPV_CTRL_REG(s).f.extend = 1u;
    }
}

static void verify_kpv_readback(void) {
    for (unsigned int s = 0; s < KPV_NUM_SLOTS; s++) {
        for (unsigned int w = 0; w < KPV_WORDS_PER_SLOT; w++) {
            uint32_t expected = KEY_PATTERN(s, w);
            uint32_t v = KPV_KEY_WORD_REG(s, w).w;
            if (v != expected) {
                TEST_FAIL("KPV key slot %u word %u readback: expected 0x%08X, got 0x%08X", s, w,
                          expected, v);
            }
        }
        if (KPV_CTRL_REG(s).f.last_dword != KPV_WORDS_PER_SLOT - 1u ||
            KPV_CTRL_REG(s).f.extend != 1u) {
            TEST_FAIL("KPV CTRL slot %u readback mismatch (val=0x%08X)", s,
                      (unsigned)KPV_CTRL_REG(s).w);
        }
    }
}

static void verify_all_zero_after_wipe(void) {
    for (unsigned int s = 0; s < KPV_NUM_SLOTS; s++) {
        for (unsigned int w = 0; w < KPV_WORDS_PER_SLOT; w++) {
            uint32_t v = KPV_KEY_WORD_REG(s, w).w;
            if (v != 0u) {
                TEST_FAIL("KPV key slot %u word %u not zero after wipe: 0x%08X", s, w, v);
            }
        }
        if (KPV_CTRL_REG(s).w != 0u) {
            TEST_FAIL("KPV CTRL slot %u not zero after wipe: 0x%08X", s,
                      (unsigned)KPV_CTRL_REG(s).w);
        }
    }
    if (KPV_SCRAMBLER_KEY_REG.w != 0u || KPV_SCRAMBLER_CTRL_REG.w != 0u) {
        TEST_FAIL("KPV scrambler not zero after wipe: key=0x%08X ctrl=0x%08X",
                  (unsigned)KPV_SCRAMBLER_KEY_REG.w, (unsigned)KPV_SCRAMBLER_CTRL_REG.w);
    }
}

static void clear_wipe_state_irq(void) {
    km_csr__irq_status_reg_t w1c = {0};
    w1c.f.wipe_state = 1;
    rom_kmcsr_irq_status_clear(w1c.w);
}

int main(void) {
    TEST_INIT();
    if (!tb_set_timeout(150000)) TEST_FAIL("timeout");

    /* Enable WIPE_STATE IRQ */
    km_csr__irq_enable_reg_t en = {.w = KMCSR_IRQ_ENABLE_REG.w};
    en.f.wipe_state_en = 1;
    KMCSR_IRQ_ENABLE_REG.w = en.w;
    rom_kmcsr_irq_status_clear(0xFFFFFFFFu);

    /* -----------------------------------------------------------------------
     * Subtest 1: Unscrambled data — scrambler off, fill KPV, wipe, verify zero.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("Wipe with unscrambled data");
    KPV_SCRAMBLER_KEY_REG.w = 0xDEADBEEFu;
    KPV_SCRAMBLER_CTRL_REG.f.enable = 0u;

    fill_kpv_and_ctrl();
    verify_kpv_readback();
    if (KPV_SCRAMBLER_KEY_REG.w != 0xDEADBEEFu) {
        TEST_FAIL("Scrambler key readback: expected 0xDEADBEEF, got 0x%08X",
                  (unsigned)KPV_SCRAMBLER_KEY_REG.w);
    }

    if (!tb_wipe_trigger(10000u)) TEST_FAIL("TB_CMD_WIPE_TRIGGER failed");
    {
        km_csr__irq_status_reg_t status_reg = {.w = rom_kmcsr_irq_status_read()};
        if (!status_reg.f.wipe_state) {
            TEST_FAIL("IRQ_STATUS.WIPE_STATE not set after wipe");
        }
    }
    verify_all_zero_after_wipe();
    clear_wipe_state_irq();
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * Subtest 2: Scrambled data — enable and lock scrambler, fill KPV, wipe, verify zero.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("Wipe with scrambled data (scrambler enabled and locked)");
    KPV_SCRAMBLER_KEY_REG.w = 0xDEADBEEFu;
    KPV_SCRAMBLER_CTRL_REG.f.enable = 1u;
    KPV_SCRAMBLER_CTRL_REG.f.lock = 1u;

    fill_kpv_and_ctrl();
    verify_kpv_readback();

    if (!tb_wipe_trigger(10000u)) TEST_FAIL("TB_CMD_WIPE_TRIGGER failed");
    {
        km_csr__irq_status_reg_t status_reg = {.w = rom_kmcsr_irq_status_read()};
        if (!status_reg.f.wipe_state) {
            TEST_FAIL("IRQ_STATUS.WIPE_STATE not set after wipe");
        }
    }
    verify_all_zero_after_wipe();
    clear_wipe_state_irq();
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
