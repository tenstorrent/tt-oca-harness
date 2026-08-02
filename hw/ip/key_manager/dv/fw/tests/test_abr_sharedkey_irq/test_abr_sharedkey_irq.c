/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_abr_sharedkey_irq.c
 * @brief Adams Bridge ML-KEM shared-key interrupt test.
 *
 * Exercises the full IRQ delivery path:
 *   key-ready event hwsets IRQ_STATUS.key_valid → abr_mlkem_sharedkey_irq =
 *   IRQ_STATUS & IRQ_ENABLE → PicoRV32 bit 5 → rom_irq() → ISR clears
 *   IRQ_STATUS (W1C) and sets g_abr_sk_notify_pending.
 *
 * Subtests:
 *   1. Gating: with IRQ disabled (reset default), loading a key sets the sticky
 *      IRQ_STATUS bit but the masked interrupt stays low (IRQ_ENABLE=0), so no
 *      IRQ is delivered.
 *   2. Delivery: with IRQ enabled, loading a key sets IRQ_STATUS and the ISR
 *      fires once; g_abr_sk_notify_pending is set to 1.
 *   3. KEY_VALID stays set — ISR did not consume the key.
 *   4. No re-fire — the ISR cleared the sticky IRQ_STATUS bit, so the interrupt
 *      does not fire again while KEY_VALID and IRQ_ENABLE both remain set.
 *   5. Consume key via rom_abr_mlkem_sharedkey_read(); KEY_VALID is cleared and
 *      the captured values match the loaded pattern (IRQ state untouched).
 *   6. Next key re-fires the IRQ — a second key load re-sets IRQ_STATUS and the
 *      ISR fires again (IRQ_ENABLE stayed enabled the whole time).
 *
 * This test provides its own rom_irq(); the firmware Makefile excludes
 * rom_isr.c for it (see the rom_irq-override test list).  g_abr_sk_notify_pending
 * is also defined here (not in rom_isr.c) since that file is excluded.
 *
 * Run: make run_fw FW_TEST=test_abr_sharedkey_irq
 */

#include "test_common.h"
#include "rom_isr.h"
#include "rom_picorv32.h"
#include "rom_sideload.h"
#include "rom_defs.h"
#include <stdint.h>

/* Defined here since rom_isr.c is excluded; extern decl is in rom_isr.h. */
volatile uint8_t g_abr_sk_notify_pending;

/**
 * Test's rom_irq() — sticky-status semantics.
 * On ABR bit 5: acknowledge the interrupt by clearing the sticky IRQ_STATUS bit
 * (W1C) and set the notify flag.  Do NOT consume the key (left intact for the
 * transfer command).  Mirrors the production rom_isr_abr_sharedkey() behavior.
 *
 * @param frame Saved IRQ frame.
 */
void rom_irq(rom_irq_frame_t *frame) {
    if (frame->irq_mask & PICORV32_IRQ_ABR_SHAREDKEY) {
        rom_abr_mlkem_sharedkey_irq_status_clear();
        g_abr_sk_notify_pending = 1u;
    }
}

/** Ask the testbench to write all 8 key words and pulse KEY_VALID. */
static void tb_load_shared_key(uint32_t base_pattern) {
    uint8_t wi;
    for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
        if (!tb_drbg_set_next_value(base_pattern | wi, 1000))
            TEST_FAIL("tb_drbg_set_next_value failed for word %u", (unsigned)wi);
        if (!tb_abr_sk_load_word(wi, 1000))
            TEST_FAIL("tb_abr_sk_load_word(%u) failed", (unsigned)wi);
    }
    if (!tb_abr_sk_assert_valid(1000)) TEST_FAIL("tb_abr_sk_assert_valid failed");
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(400000)) TEST_FAIL("Failed to set testbench timeout");

    printf("Adams Bridge ML-KEM Shared-Key IRQ Test (sticky-status semantics)\n");
    printf("==================================================================\n\n");

    /* Unmask all CPU IRQs. */
    rom_picorv32_maskirq(0x00000000u);

    /* ------------------------------------------------------------------
     * Subtest 1: IRQ gated by IRQ_ENABLE.key_valid_en (disabled at reset).
     *
     * Loading a key sets the sticky IRQ_STATUS bit, but with IRQ_ENABLE clear
     * the masked interrupt (IRQ_STATUS & IRQ_ENABLE) stays low, so
     * g_abr_sk_notify_pending stays 0.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("IRQ gated by enable (disabled)");
    g_abr_sk_notify_pending = 0u;
    tb_load_shared_key(0x5EED0000u);
    test_delay(500); /* ample time for spurious delivery if gating fails */
    if (g_abr_sk_notify_pending != 0u)
        TEST_FAIL("notify_pending set while IRQ_ENABLE.key_valid_en = 0");
    /* Clear the pending sticky status and consume the key so the next subtest
     * starts from a clean state. */
    rom_abr_mlkem_sharedkey_irq_status_clear();
    {
        uint32_t discard[ROM_KM_ABR_WORDS_PER_SHARE];
        rom_abr_mlkem_sharedkey_read(discard);
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 2: IRQ delivered to CPU with IRQ enabled.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("IRQ delivered to CPU (enabled)");
    rom_abr_mlkem_sharedkey_irq_enable();
    g_abr_sk_notify_pending = 0u;
    tb_load_shared_key(0xA5A50000u);

    {
        uint32_t t = 500000u;
        while (g_abr_sk_notify_pending == 0u && t--) __asm__ volatile("nop");
        if (g_abr_sk_notify_pending == 0u) TEST_FAIL("ABR shared-key IRQ never delivered to CPU");
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 3: KEY_VALID stays set — ISR did not consume the key.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("KEY_VALID stays set after IRQ (ISR does not consume)");
    if (!ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid)
        TEST_FAIL("KEY_VALID was cleared by ISR (should stay set; ISR must not consume)");
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 4: No re-fire — the ISR cleared the sticky IRQ_STATUS bit, so
     * the interrupt does not fire again even though KEY_VALID and IRQ_ENABLE
     * both remain set.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("Single delivery (ISR clears sticky IRQ_STATUS)");
    g_abr_sk_notify_pending = 0u;
    test_delay(500); /* enough time for a spurious second trigger */
    if (g_abr_sk_notify_pending != 0u)
        TEST_FAIL("IRQ re-fired unexpectedly (ISR should have cleared IRQ_STATUS)");
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 5: rom_abr_mlkem_sharedkey_read() reads and clears the key.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("Consume via rom_abr_mlkem_sharedkey_read");
    {
        uint32_t sk_out[ROM_KM_ABR_WORDS_PER_SHARE];
        rom_abr_mlkem_sharedkey_read(sk_out);

        uint8_t wi;
        for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
            uint32_t expected = 0xA5A50000u | wi;
            if (sk_out[wi] != expected)
                TEST_FAIL("key[%u]: got=0x%08X expected=0x%08X", (unsigned)wi, sk_out[wi],
                          expected);
        }
        if (ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid)
            TEST_FAIL("KEY_VALID not cleared after consume (ctrl=0x%08X)",
                      (unsigned)ROM_ABR_MLKEM_SK_CTRL_REG.w);
        TEST_LOG("  All 8 key words match; KEY_VALID cleared");
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 6: Second key load fires the IRQ again — IRQ_ENABLE stayed
     * enabled, so the new key-ready event re-sets the sticky IRQ_STATUS bit.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("IRQ re-fires for second key (status re-set by HW)");
    g_abr_sk_notify_pending = 0u;
    tb_load_shared_key(0xBEEF0000u);

    {
        uint32_t t = 500000u;
        while (g_abr_sk_notify_pending == 0u && t--) __asm__ volatile("nop");
        if (g_abr_sk_notify_pending == 0u)
            TEST_FAIL("Second key IRQ not delivered (HW did not re-set IRQ_STATUS)");
    }
    {
        uint32_t discard[ROM_KM_ABR_WORDS_PER_SHARE];
        rom_abr_mlkem_sharedkey_read(discard);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
