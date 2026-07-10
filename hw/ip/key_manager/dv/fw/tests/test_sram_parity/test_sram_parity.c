/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_sram_parity.c
 * @brief SRAM parity error detection test
 *
 * Verifies that SRAM parity errors are detected correctly:
 * 1. No parity error with correct parity (injection disabled)
 * 2. Parity error detected when injection is enabled
 * 3. Parity error clears when injection is disabled
 *
 * This test uses the testbench command interface to control parity
 * error injection, and reads KMCSR IRQ_STATUS to verify detection.
 *
 * Run with:
 *   make run_fw FW_TEST=test_sram_parity
 */

#include "test_common.h"

#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "irq_common.h"

/* SRAM test addresses (avoid first 0x100 bytes used by test protocol) */
#define SRAM_TEST_BASE (SRAM_BASE + 0x100)

/**
 * Read IRQ_STATUS register.
 */
static inline uint32_t read_irq_status(void) {
    return KMCSR_IRQ_STATUS_REG.w;
}

/**
 * Clear IRQ_STATUS by writing 1s to sticky bits.
 */
static inline void clear_irq_status(void) {
    km_csr__irq_status_reg_t clear_val = {0};
    clear_val.f.rom_parity_err = 1;
    clear_val.f.sram_parity_err = 1;
    KMCSR_IRQ_STATUS_REG.w = clear_val.w;
}

int main(void) {
    uint32_t irq_status;
    uint32_t test_data;
    uint32_t readback;

    TEST_INIT();

    /* Test 1: Verify no parity error with correct parity */
    TEST_SUBTEST_START("No error with correct parity");
    {
        /* Ensure parity injection is disabled */
        if (!tb_sram_parity_inject_disable()) {
            TEST_LOG("  Warning: Could not disable parity injection");
        }

        /* Clear any previous parity errors */
        clear_irq_status();

        /* Write to SRAM - this establishes known good data with correct parity */
        test_data = 0xDEADBEEF;
        test_write32(SRAM_TEST_BASE, test_data);
        TEST_LOG("  SRAM write: 0x%08X", test_data);

        /* Read back from SRAM - should not cause parity error */
        readback = test_read32(SRAM_TEST_BASE);
        TEST_LOG("  SRAM read:  0x%08X", readback);
        TEST_ASSERT_EQ(readback, test_data, "SRAM readback");

        /* Small delay for error to propagate if any */
        test_delay(10);

        /* Check IRQ_STATUS - SRAM_PARITY_ERR should be 0 */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS: 0x%08X", irq_status);

        if (KMCSR_IRQ_STATUS_REG.f.sram_parity_err) {
            TEST_FAIL("Unexpected SRAM parity error with correct parity");
        }
    }
    TEST_SUBTEST_PASS();

    /* Test 2: Verify parity error detection with injection enabled */
    TEST_SUBTEST_START("Parity error detection");
    {
        /* Enable parity error injection via testbench command */
        TEST_LOG("  Enabling SRAM parity injection...");
        if (!tb_sram_parity_inject_enable()) {
            TEST_FAIL("Failed to enable SRAM parity injection");
        }

        /* Clear any previous parity errors */
        clear_irq_status();

        /* Write to SRAM first (to ensure data is there) */
        test_data = 0xCAFEBABE;
        test_write32(SRAM_TEST_BASE, test_data);
        test_delay(10);

        /* Read from SRAM - should trigger parity error */
        readback = test_read32(SRAM_TEST_BASE);
        TEST_LOG("  SRAM read with bad parity: 0x%08X", readback);

        /* Small delay for error to propagate */
        test_delay(10);

        /* Check IRQ_STATUS - SRAM_PARITY_ERR should be 1 */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS: 0x%08X", irq_status);

        if (!KMCSR_IRQ_STATUS_REG.f.sram_parity_err) {
            TEST_FAIL("SRAM parity error not detected (IRQ_STATUS=0x%08X)", irq_status);
        }
        TEST_LOG("  SRAM parity error correctly detected");
    }
    TEST_SUBTEST_PASS();

    /* Test 3: Verify parity error clears when injection disabled */
    TEST_SUBTEST_START("Error clears after injection disabled");
    {
        /* Disable parity error injection */
        TEST_LOG("  Disabling SRAM parity injection...");
        if (!tb_sram_parity_inject_disable()) {
            TEST_FAIL("Failed to disable SRAM parity injection");
        }

        /*
         * Wait for any in-flight transactions to complete.
         * Unlike ROM (where instruction fetches happen constantly),
         * SRAM accesses are explicit, so we don't need as long a delay.
         */
        test_delay(100);

        /* Clear IRQ_STATUS - write 1 to clear sticky bits */
        clear_irq_status();
        test_delay(10); /* Wait for clear to propagate */

        /* Verify clear took effect for SRAM parity bit */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS after clear: 0x%08X", irq_status);

        /* Note: We ignore ROM parity errors as they may be from instruction fetches */
        uint32_t sram_parity_bit = KMCSR_IRQ_STATUS_REG.f.sram_parity_err ? 1 : 0;
        TEST_LOG("  SRAM parity bit after clear: %d", sram_parity_bit);

        if (sram_parity_bit) {
            /* Bit might still be set from in-flight transactions.
             * Wait longer and clear again. */
            test_delay(100);
            clear_irq_status();
            test_delay(10);
            irq_status = read_irq_status();
            TEST_LOG("  IRQ_STATUS after second clear: 0x%08X", irq_status);
            sram_parity_bit = KMCSR_IRQ_STATUS_REG.f.sram_parity_err ? 1 : 0;
        }

        /* SRAM parity bit should be cleared after waiting and clearing */
        if (sram_parity_bit) {
            TEST_FAIL("SRAM parity error persists after injection disabled and clear");
        }

        /* Now do a fresh SRAM write/read with good parity to verify */
        test_data = 0x12345678;
        test_write32(SRAM_TEST_BASE + 0x10, test_data);
        test_delay(10);
        readback = test_read32(SRAM_TEST_BASE + 0x10);
        TEST_LOG("  SRAM write: 0x%08X, read: 0x%08X", test_data, readback);
        TEST_ASSERT_EQ(readback, test_data, "SRAM readback after injection disabled");

        /* Small delay for any error to propagate */
        test_delay(10);

        /* Check IRQ_STATUS - should have no new SRAM parity error */
        irq_status = read_irq_status();
        TEST_LOG("  Final IRQ_STATUS: 0x%08X", irq_status);

        if (KMCSR_IRQ_STATUS_REG.f.sram_parity_err) {
            TEST_FAIL("New SRAM parity error after injection disabled");
        }

        TEST_LOG("  SRAM parity injection disabled and verified");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
