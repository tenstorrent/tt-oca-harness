/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_overflow_sep.c
 * @brief Mailbox FIFO overflow test - SEP side (firmware-driven)
 *
 * Verifies that SEP-side mailbox overflow conditions set status bits, trigger IRQs,
 * and return configurable AXI responses (SLVERR default, OKAY configurable).
 *
 * Tests:
 * - SEP-side: Write to full inbound FIFO sets status bits, triggers IRQ, returns SLVERR
 * - Configuration: CTRL register controls SLVERR vs OKAY response
 * - Status bits: Overflow status bits are write-1-to-clear (no read side-effects)
 * - IRQ routing: SEP-side IRQs go to testbench interface
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_overflow_sep
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#include "km_mailbox_sep_regs.h"

/* Register access macros using struct types */
#define MBOX_READ_DATA_REG \
    (*(volatile km_mailbox_km__read_data_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR)
#define MBOX_STATUS_REG \
    (*(volatile km_mailbox_km__status_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR)
#define MBOX_IRQ_STATUS_REG \
    (*(volatile km_mailbox_km__irq_status_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_IRQ_STATUS_BASE_ADDR)
#define MBOX_IRQ_ENABLE_REG \
    (*(volatile km_mailbox_km__irq_enable_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_IRQ_ENABLE_BASE_ADDR)
#define MBOX_CTRL_REG \
    (*(volatile km_mailbox_km__ctrl_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_CTRL_BASE_ADDR)

/* Helper functions to construct SEP mailbox register values from struct fields.
 * NOTE: KM_MAILBOX_SEP_* types are ONLY for constructing bit patterns to pass
 * to testbench commands. SEP mailbox registers are NOT accessible from KM and
 * must be accessed via testbench command interface (tb_sep_mbox_* functions).
 */
static inline uint32_t sep_mbox_irq_enable_inbound_overflow(void) {
    KM_MAILBOX_SEP_IRQ_ENABLE_REG_reg_u enable_val = {0};
    enable_val.f.inbound_overflow_en = 1;
    return enable_val.w;
}

static inline uint32_t sep_mbox_ctrl_inbound_overflow_resp(void) {
    KM_MAILBOX_SEP_CTRL_REG_reg_u ctrl_val = {0};
    ctrl_val.f.inbound_overflow_resp = 1;
    return ctrl_val.w;
}

/* Mailbox FIFO depth - must match RTL parameter in km_mailbox.sv */
#define MAILBOX_DEPTH 16

/* AXI response codes */
#define AXI_OKAY 0x00
#define AXI_SLVERR 0x02

/**
 * Read mailbox STATUS register.
 */
static inline uint32_t mbox_read_status(void) {
    return MBOX_STATUS_REG.w;
}

/**
 * Check if inbound FIFO is full.
 */
static inline int mbox_inbound_full(void) {
    return MBOX_STATUS_REG.f.inbound_full != 0;
}

/**
 * Check if inbound FIFO is empty.
 */
static inline int mbox_inbound_empty(void) {
    return MBOX_STATUS_REG.f.inbound_empty != 0;
}

/**
 * Read data from mailbox READ_DATA register (reads from inbound FIFO).
 */
static inline uint32_t mbox_read_data(void) {
    return MBOX_READ_DATA_REG.w;
}

/**
 * Clear overflow status bits (write-1-to-clear).
 */
static inline void mbox_clear_overflow_status(void) {
    /* Note: SEP-side overflow uses SEP-side STATUS, cleared via testbench */
}

int main(void) {
    uint32_t write_resp;

    TEST_INIT();

    /* Set timeout */
    if (!tb_set_timeout(400000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /*=========================================================================
     * Test 1: SEP-side overflow - Write to full inbound FIFO returns SLVERR,
     *         sets status bits, triggers IRQ, and preserves existing data
     *=========================================================================*/
    TEST_SUBTEST_START("SEP-side overflow returns SLVERR and preserves data");
    {
        uint32_t read_data;
        uint32_t expected_data[MAILBOX_DEPTH];
        uint32_t overflow_data = 0xDEADBEEF;

        /* Clear any pending status bits */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.inbound_overflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox overflow status");
            }
        }

        /* Enable SEP mailbox overflow IRQ */
        if (!tb_sep_mbox_irq_enable(sep_mbox_irq_enable_inbound_overflow(), 1000)) {
            TEST_FAIL("Failed to enable SEP mailbox overflow IRQ");
        }
        TEST_LOG("  Enabled SEP mailbox inbound overflow interrupt");

        /* Verify initial state */
        TEST_ASSERT_EQ(MBOX_STATUS_REG.f.inbound_full, 0,
                       "Inbound FIFO should not be full initially");

        /* Fill inbound FIFO with known data pattern via SEP-side writes */
        TEST_LOG("  Filling mailbox inbound FIFO with %d entries via SEP-side...", MAILBOX_DEPTH);
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            expected_data[i] = 0x1000 + i;
            if (!tb_sep_mbox_write_with_resp(expected_data[i], &write_resp, 1000)) {
                TEST_FAIL("Failed to write entry %u to FIFO", i);
            }
            TEST_ASSERT_EQ(write_resp, AXI_OKAY, "Write should succeed");
            test_delay(5); /* Small delay between writes */
        }
        TEST_LOG("  FIFO filled with %d entries", MAILBOX_DEPTH);

        /* Verify FIFO is full */
        test_delay(10);
        TEST_ASSERT(mbox_inbound_full(), "Inbound FIFO should be full");

        /* Attempt overflow write - should return SLVERR */
        TEST_LOG("  Attempting overflow write with 0x%08X...", overflow_data);
        if (!tb_sep_mbox_write_with_resp(overflow_data, &write_resp, 1000)) {
            TEST_FAIL("Failed to attempt write to full FIFO");
        }

        TEST_LOG("  SEP write response: 0x%02X (0=OKAY, 2=SLVERR)", write_resp);
        TEST_ASSERT_EQ(write_resp, AXI_SLVERR, "SEP-side write to full FIFO should return SLVERR");

        /* Verify FIFO is still full */
        test_delay(10);
        TEST_ASSERT(mbox_inbound_full(), "Inbound FIFO should still be full");

        /* Check SEP-side STATUS register for overflow status bit */
        uint32_t sep_status_val;
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        TEST_LOG("  SEP-side STATUS register: 0x%08X", sep_status_val);
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT(status_reg.f.inbound_overflow,
                        "SEP-side STATUS.INBOUND_OVERFLOW should be set after overflow");
        }

        /* Check SEP-side IRQ signal is asserted */
        uint32_t sep_irq_signal;
        if (!tb_sep_mbox_irq_check(&sep_irq_signal, 1000)) {
            TEST_FAIL("Failed to check SEP mailbox IRQ signal");
        }
        TEST_LOG("  SEP-side IRQ signal: %d (1=asserted)", sep_irq_signal);
        TEST_ASSERT_EQ(sep_irq_signal, 1, "SEP-side IRQ signal should be asserted after overflow");

        /* Read back all data and verify it matches original (overflow data should be dropped) */
        TEST_LOG("  Reading back FIFO contents to verify data integrity...");
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            read_data = mbox_read_data();
            TEST_LOG("    Entry %u: read=0x%08X, expected=0x%08X", i, read_data, expected_data[i]);
            if (read_data != expected_data[i]) {
                TEST_FAIL("FIFO entry %u mismatch: read=0x%08X, expected=0x%08X (overflow write "
                          "should be dropped)",
                          i, read_data, expected_data[i]);
            }
            test_delay(5); /* Small delay between reads */
        }

        /* Verify FIFO is now empty */
        test_delay(10);
        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO should be empty after reading all data");

        /* Clear SEP-side overflow status bit (W1C) */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.inbound_overflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox overflow status");
            }
        }
        test_delay(5);
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT_EQ(status_reg.f.inbound_overflow, 0,
                           "SEP-side STATUS.INBOUND_OVERFLOW should be clear after W1C");
        }

        TEST_LOG("  Overflow data was dropped, original data preserved, status/IRQ bits verified");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 2: Configuration bits - Test CTRL register for OKAY vs SLVERR response
     *=========================================================================*/
    TEST_SUBTEST_START("Configuration bits control overflow response");
    {
        uint32_t sep_status_val;

        TEST_LOG("  Testing SEP-side (inbound) overflow response configuration...");

        /* Clear any pending status bits */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.inbound_overflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox overflow status");
            }
        }

        /* Fill inbound FIFO */
        TEST_LOG("  Filling inbound FIFO to test overflow response configuration...");
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            if (!tb_sep_mbox_write_with_resp(0x1000 + i, &write_resp, 1000)) {
                TEST_FAIL("Failed to fill FIFO");
            }
        }
        test_delay(10);
        TEST_ASSERT(mbox_inbound_full(), "FIFO should be full");

        /* Test default behavior (SLVERR) - SEP-side CTRL controls inbound overflow */
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        TEST_LOG("  SEP-side STATUS register (initial): 0x%08X", sep_status_val);

        /* SEP-side write to full inbound FIFO - default should be SLVERR */
        if (!tb_sep_mbox_write_with_resp(0xDEADBEEF, &write_resp, 1000)) {
            TEST_FAIL("Failed to attempt overflow write");
        }
        TEST_LOG("  SEP write response (default): 0x%02X (0=OKAY, 2=SLVERR)", write_resp);
        TEST_ASSERT_EQ(write_resp, AXI_SLVERR, "SEP-side overflow should return SLVERR by default");

        test_delay(10);
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        TEST_LOG("  SEP-side STATUS register: 0x%08X", sep_status_val);
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT(status_reg.f.inbound_overflow,
                        "SEP-side STATUS.INBOUND_OVERFLOW should be set after overflow");
        }

        /* Configure to return OKAY */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.inbound_overflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox overflow status");
            }
        }
        if (!tb_sep_mbox_ctrl_write(sep_mbox_ctrl_inbound_overflow_resp(), 1000)) {
            TEST_FAIL("Failed to write SEP mailbox CTRL register");
        }
        TEST_LOG("  Configured SEP-side CTRL.INBOUND_OVERFLOW_RESP to OKAY");

        /* Drain and refill FIFO */
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            mbox_read_data();
        }
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            if (!tb_sep_mbox_write_with_resp(0x2000 + i, &write_resp, 1000)) {
                TEST_FAIL("Failed to refill FIFO");
            }
        }
        test_delay(10);
        TEST_ASSERT(mbox_inbound_full(), "FIFO should be full again");

        /* Write with OKAY response configured */
        if (!tb_sep_mbox_write_with_resp(0xCAFEBABE, &write_resp, 1000)) {
            TEST_FAIL("Failed to attempt overflow write");
        }
        TEST_LOG("  SEP write response (OKAY configured): 0x%02X (0=OKAY, 2=SLVERR)", write_resp);
        TEST_ASSERT_EQ(write_resp, AXI_OKAY,
                       "SEP-side overflow should return OKAY when configured");

        test_delay(10);
        /* Verify overflow status bit is still set even with OKAY response */
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT(status_reg.f.inbound_overflow,
                        "SEP-side STATUS.INBOUND_OVERFLOW should be set even with OKAY response");
        }

        /* Restore default (SLVERR) */
        if (!tb_sep_mbox_ctrl_write(0, 1000)) {
            TEST_FAIL("Failed to restore SEP mailbox CTRL register to default");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.inbound_overflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox overflow status");
            }
        }

        /* Drain FIFO */
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            mbox_read_data();
        }

        TEST_LOG("  Configuration bits verified (SLVERR default and OKAY configurable)");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
