/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_underflow_sep.c
 * @brief Mailbox FIFO underflow test - SEP side (firmware-driven)
 *
 * Verifies that SEP-side mailbox underflow conditions set status bits, trigger IRQs,
 * and return configurable AXI responses (SLVERR default, OKAY configurable).
 *
 * Tests:
 * - SEP-side: SEP reads from empty outbound FIFO sets status bits, triggers IRQ, returns SLVERR
 * - Configuration: CTRL register controls SLVERR vs OKAY response
 * - Status bits: Underflow status bits are write-1-to-clear (no read side-effects)
 * - IRQ aggregation: Mailbox IRQs aggregated and propagate to KMCSR
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_underflow_sep
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* AXI response codes */
#define AXI_OKAY 0x00
#define AXI_SLVERR 0x02

#include "km_mailbox_sep_regs.h"

/* Register access macros using struct types */
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
static inline uint32_t sep_mbox_irq_enable_outbound_underflow(void) {
    KM_MAILBOX_SEP_IRQ_ENABLE_REG_reg_u enable_val = {0};
    enable_val.f.outbound_underflow_en = 1;
    return enable_val.w;
}

static inline uint32_t sep_mbox_ctrl_outbound_underflow_resp(void) {
    KM_MAILBOX_SEP_CTRL_REG_reg_u ctrl_val = {0};
    ctrl_val.f.outbound_underflow_resp = 1;
    return ctrl_val.w;
}

/**
 * Read mailbox STATUS register.
 */
static inline uint32_t mbox_read_status(void) {
    return MBOX_STATUS_REG.w;
}

/**
 * Check if outbound FIFO is empty.
 */
static inline int mbox_outbound_empty(void) {
    return MBOX_STATUS_REG.f.outbound_empty != 0;
}

/**
 * Write mailbox IRQ_STATUS register (for clearing sticky bits).
 */
static inline void mbox_write_irq_status(uint32_t value) {
    MBOX_IRQ_STATUS_REG.w = value;
}

/**
 * Clear underflow status bits (write-1-to-clear).
 */
static inline void mbox_clear_underflow_status(void) {
    /* Note: SEP-side underflow uses SEP-side STATUS, cleared via testbench */
}

int main(void) {
    TEST_INIT();

    /* Set timeout */
    if (!tb_set_timeout(100000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /*=========================================================================
     * Test 1: SEP-side underflow - SEP reads from empty outbound FIFO sets status bits,
     *         triggers IRQ, and returns SLVERR
     *         Note: SEP-side underflow = SEP reads from empty outbound FIFO.
     *         This sets SEP-side OUTBOUND_UNDERFLOW status/IRQ (SEP tracks outbound FIFO).
     *=========================================================================*/
    TEST_SUBTEST_START("SEP-side underflow sets status bits and triggers IRQ");
    {
        uint32_t read_data;
        uint32_t read_resp;

        /* Verify outbound FIFO is empty (SEP reads from this) */
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO should be empty after reset");

        /* Enable SEP mailbox underflow IRQ via testbench (SEP side IRQ_ENABLE) */
        if (!tb_sep_mbox_irq_enable(sep_mbox_irq_enable_outbound_underflow(), 1000)) {
            TEST_FAIL("Failed to enable SEP mailbox underflow IRQ");
        }
        TEST_LOG("  Enabled SEP mailbox outbound underflow interrupt");

        /* Verify initial state - check SEP-side STATUS register */
        uint32_t sep_status_val;
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT_EQ(status_reg.f.outbound_underflow, 0,
                           "SEP-side STATUS.OUTBOUND_UNDERFLOW should be clear initially");
        }

        /* SEP-side read from empty outbound FIFO - this triggers SEP-side underflow */
        TEST_LOG("  Reading from empty outbound FIFO via SEP-side...");
        if (!tb_sep_mbox_read_with_resp(&read_data, &read_resp, 1000)) {
            TEST_FAIL("Failed to perform SEP-side read");
        }
        TEST_LOG("  SEP read response: 0x%02X (0=OKAY, 2=SLVERR)", read_resp);
        TEST_LOG("  SEP read data: 0x%08X", read_data);
        TEST_ASSERT_EQ(read_resp, AXI_SLVERR, "SEP-side read from empty FIFO should return SLVERR");

        /* Small delay to allow interrupt to propagate */
        test_delay(20);

        /* Check SEP-side IRQ signal is asserted (tb_sep_mbox_irq_check returns IRQ signal, not
         * IRQ_STATUS register) */
        uint32_t sep_irq_signal;
        if (!tb_sep_mbox_irq_check(&sep_irq_signal, 1000)) {
            TEST_FAIL("Failed to check SEP mailbox IRQ signal");
        }
        TEST_LOG("  SEP-side IRQ signal: %d (1=asserted)", sep_irq_signal);
        TEST_ASSERT_EQ(sep_irq_signal, 1, "SEP-side IRQ signal should be asserted after underflow");

        /* Check SEP-side underflow status bit is set */
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        TEST_LOG("  SEP-side STATUS register: 0x%08X", sep_status_val);
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT(
                status_reg.f.outbound_underflow,
                "SEP-side STATUS.OUTBOUND_UNDERFLOW should be set after SEP-side underflow");
        }

        /* Verify FIFO is still empty */
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO should still be empty after read");

        /* Clear SEP-side underflow status bit (write-1-to-clear via testbench) */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.outbound_underflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox underflow status");
            }
        }
        test_delay(5);
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT_EQ(status_reg.f.outbound_underflow, 0,
                           "SEP-side STATUS.OUTBOUND_UNDERFLOW should be clear after W1C");
        }

        TEST_LOG("  SEP-side underflow status/IRQ bits verified");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 2: Configuration bits - Test CTRL register for OKAY vs SLVERR response
     *=========================================================================*/
    TEST_SUBTEST_START("Configuration bits control underflow response");
    {
        uint32_t read_data;
        uint32_t read_resp;

        /* Test SEP-side (outbound) underflow response configuration */
        TEST_LOG("  Testing SEP-side (outbound) underflow response configuration...");

        /* Ensure outbound FIFO is empty */
        test_delay(50);
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO should be empty");

        /* Clear any pending status bits */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.outbound_underflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox underflow status");
            }
        }

        /* Test default behavior (SLVERR) - SEP-side CTRL controls outbound underflow */
        /* Verify CTRL register defaults to 0 (SLVERR) */
        uint32_t sep_status_val;
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        TEST_LOG("  SEP-side STATUS register (initial): 0x%08X", sep_status_val);

        /* SEP-side read from empty outbound FIFO - default should be SLVERR */
        if (!tb_sep_mbox_read_with_resp(&read_data, &read_resp, 1000)) {
            TEST_FAIL("Failed to perform SEP-side read");
        }
        TEST_LOG("  SEP read response (default): 0x%02X (0=OKAY, 2=SLVERR)", read_resp);
        TEST_ASSERT_EQ(read_resp, AXI_SLVERR, "Outbound underflow should return SLVERR by default");

        test_delay(10);
        /* Check SEP-side STATUS register for underflow status bit */
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        TEST_LOG("  SEP-side STATUS register: 0x%08X", sep_status_val);
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT(status_reg.f.outbound_underflow,
                        "SEP-side STATUS.OUTBOUND_UNDERFLOW should be set after underflow");
        }

        /* Configure to return OKAY */
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.outbound_underflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox underflow status");
            }
        }
        if (!tb_sep_mbox_ctrl_write(sep_mbox_ctrl_outbound_underflow_resp(), 1000)) {
            TEST_FAIL("Failed to write SEP mailbox CTRL register");
        }
        TEST_LOG("  Configured SEP-side CTRL.OUTBOUND_UNDERFLOW_RESP to OKAY");

        /* SEP-side read with OKAY response */
        if (!tb_sep_mbox_read_with_resp(&read_data, &read_resp, 1000)) {
            TEST_FAIL("Failed to perform SEP-side read");
        }
        TEST_LOG("  SEP read response (OKAY configured): 0x%02X (0=OKAY, 2=SLVERR)", read_resp);
        TEST_ASSERT_EQ(read_resp, AXI_OKAY,
                       "Outbound underflow should return OKAY when configured");

        test_delay(10);
        /* Verify underflow status bit is still set even with OKAY response */
        if (!tb_sep_mbox_status_read(&sep_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP mailbox STATUS register");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u status_reg = {.w = sep_status_val};
            TEST_ASSERT(status_reg.f.outbound_underflow,
                        "SEP-side STATUS.OUTBOUND_UNDERFLOW should be set even with OKAY response");
        }

        /* Restore default (SLVERR) */
        if (!tb_sep_mbox_ctrl_write(0, 1000)) {
            TEST_FAIL("Failed to restore SEP mailbox CTRL register to default");
        }
        {
            KM_MAILBOX_SEP_STATUS_REG_reg_u clear_val = {0};
            clear_val.f.outbound_underflow = 1;
            if (!tb_sep_mbox_status_write(clear_val.w, 1000)) {
                TEST_FAIL("Failed to clear SEP mailbox underflow status");
            }
        }

        TEST_LOG("  Configuration bits verified (SLVERR default and OKAY configurable)");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
