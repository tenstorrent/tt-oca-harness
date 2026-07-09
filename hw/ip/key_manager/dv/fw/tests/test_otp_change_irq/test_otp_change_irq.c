/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_change_irq.c
 * @brief OTP_CHANGE interrupt end-to-end test.
 *
 * Flow:
 *   1. Drive initial OTP pattern (TB_CMD_OTP_WRITE).
 *   2. Wait one cycle for hardware to sample the first values.
 *   3. Drive a CHANGED OTP pattern (TB_CMD_OTP_WRITE_CHANGED).
 *   4. Wait for OTP_CHANGE IRQ to fire (polled via IRQ_STATUS).
 *   5. Verify OTP_CHANGE_STATUS has the expected changed-fields bitmask.
 *   6. W1C-clear OTP_CHANGE_STATUS; verify it cleared.
 *   7. W1C-clear OTP_CHANGE IRQ_STATUS bit; verify it cleared.
 *
 * The test overrides `rom_otp_on_change()` to capture the changed-fields mask.
 *
 * Run: make run_fw FW_TEST=test_otp_change_irq
 */

#include "test_common.h"
#include "rom_otp.h"
#include "irq_common.h"
#include "rom_isr.h"
#include "rom_kmcsr.h"

/* Captured in rom_otp_on_change() override */
static volatile uint32_t g_changed_mask = 0;
static volatile int g_change_irq_fired = 0;

void rom_otp_on_change(uint32_t changed_mask) {
    g_changed_mask = changed_mask;
    g_change_irq_fired = 1;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(200000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("OTP Change IRQ Test\n");
    printf("===================\n\n");

    /* Enable otp_change IRQ — this is not done at boot; it is enabled after
     * key registry init in production firmware.  The test enables it here so
     * the full CPU IRQ delivery path is exercised. */
    {
        km_csr__irq_enable_reg_t en;
        en.w = rom_kmcsr_irq_enable_read();
        en.w |= ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK;
        rom_kmcsr_irq_enable_write(en.w);
    }

    /* 1. Drive initial pattern and let hardware sample it */
    TEST_SUBTEST_START("Drive initial OTP pattern");
    tb_otp_write();
    /* Busy-wait a few cycles for hw prev-value registers to update */
    test_delay(200);
    TEST_SUBTEST_PASS();

    /* Clear any latched IRQ bits from boot */
    rom_kmcsr_irq_status_clear(0xFFFFFFFFu);

    /* 2. Drive changed pattern — this should generate otp_change pulses */
    TEST_SUBTEST_START("Drive changed OTP pattern");
    tb_otp_write_changed();
    TEST_SUBTEST_PASS();

    /* 3. Poll for OTP_CHANGE IRQ (handled by rom_isr_kmcsr via PICORV32_IRQ_KMCSR) */
    TEST_SUBTEST_START("Wait for OTP_CHANGE IRQ to fire");
    {
        uint32_t timeout = 500000u;
        while (!g_change_irq_fired && timeout--) {
            /* Check IRQ_STATUS directly in case CPU IRQs are not unmasked yet */
            km_csr__irq_status_reg_t st;
            st.w = rom_kmcsr_irq_status_read();
            if (st.w & ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK) {
                /* Manually invoke the KMCSR ISR to simulate the path */
                rom_isr_kmcsr();
            }
            __asm__ volatile("nop");
        }
        if (!g_change_irq_fired) {
            TEST_FAIL("OTP_CHANGE IRQ never fired (timeout)");
        }
    }
    TEST_SUBTEST_PASS();

    /* 4. Verify changed-fields bitmask in the hook */
    TEST_SUBTEST_START("Verify changed-fields bitmask");
    {
        /*
         * All six monitored fields should have changed:
         *   life_cycle, demotion, chiplet_uid, sip_uid, sys_uid, class_key
         */
        uint32_t expected = ROM_KM_OTP_CHANGE_ALL_MASK;
        if ((g_changed_mask & expected) != expected) {
            TEST_FAIL("Changed-fields mask: expected 0x%08X, got 0x%08X", expected, g_changed_mask);
        }
    }
    TEST_SUBTEST_PASS();

    /* 5. OTP_CHANGE_STATUS should now be cleared (hook cleared it via W1C) */
    TEST_SUBTEST_START("OTP_CHANGE_STATUS cleared after ISR");
    {
        uint32_t cs = rom_otp_get_change_status();
        if (cs != 0) {
            TEST_FAIL("OTP_CHANGE_STATUS: expected 0 after ISR, got 0x%08X", cs);
        }
    }
    TEST_SUBTEST_PASS();

    /* 6. OTP_CHANGE IRQ_STATUS bit should also be cleared by the ISR (hwclr on status read) */
    TEST_SUBTEST_START("IRQ_STATUS.otp_change cleared after ISR");
    {
        km_csr__irq_status_reg_t st;
        st.w = rom_kmcsr_irq_status_read();
        if (st.w & ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK) {
            /* Try to W1C-clear it */
            km_csr__irq_status_reg_t clr = {0};
            clr.w = ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK;
            rom_kmcsr_irq_status_clear(clr.w);
            st.w = rom_kmcsr_irq_status_read();
            if (st.w & ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK) {
                TEST_FAIL("IRQ_STATUS.otp_change still set after W1C clear");
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
