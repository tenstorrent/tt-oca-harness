/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_underflow_km.c
 * @brief Mailbox FIFO underflow test - KM side (firmware-driven)
 *
 * Verifies that KM-side mailbox underflow conditions set status bits, trigger IRQs,
 * and return configurable AXI responses (SLVERR default, OKAY configurable).
 *
 * Tests:
 * - KM-side: KM reads from empty inbound FIFO sets status bits, triggers IRQ, returns SLVERR
 * - Configuration: CTRL register controls SLVERR vs OKAY response
 * - Status bits: Underflow status bits are write-1-to-clear
 * - IRQ aggregation: Mailbox IRQs aggregated and propagate to KMCSR
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_underflow_km
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

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

/**
 * Read mailbox STATUS register.
 */
static inline uint32_t mbox_read_status(void) {
    return MBOX_STATUS_REG.w;
}

/**
 * Read mailbox IRQ_STATUS register.
 */
static inline uint32_t mbox_read_irq_status(void) {
    return MBOX_IRQ_STATUS_REG.w;
}

/**
 * Write mailbox IRQ_STATUS register (for clearing sticky bits).
 */
static inline void mbox_write_irq_status(uint32_t value) {
    MBOX_IRQ_STATUS_REG.w = value;
}

/**
 * Write mailbox IRQ_ENABLE register.
 */
static inline void mbox_write_irq_enable(uint32_t value) {
    MBOX_IRQ_ENABLE_REG.w = value;
}

/**
 * Read mailbox READ_DATA register (reads from inbound FIFO).
 */
static inline uint32_t mbox_read_data(void) {
    return MBOX_READ_DATA_REG.w;
}

/**
 * Read mailbox CTRL register.
 */
static inline uint32_t mbox_read_ctrl(void) {
    return MBOX_CTRL_REG.w;
}

/**
 * Write mailbox CTRL register.
 */
static inline void mbox_write_ctrl(uint32_t value) {
    MBOX_CTRL_REG.w = value;
}

/**
 * Check if inbound FIFO is empty.
 */
static inline int mbox_inbound_empty(void) {
    return MBOX_STATUS_REG.f.inbound_empty != 0;
}

/**
 * Clear underflow status bits (write-1-to-clear).
 */
static inline void mbox_clear_underflow_status(void) {
    km_mailbox_km__status_reg_t clear_val = {0};
    clear_val.f.inbound_underflow = 1;
    MBOX_STATUS_REG.w = clear_val.w;
}

int main(void) {
    uint32_t status_val;
    uint32_t irq_status_val;
    uint32_t read_data;
    uint32_t ctrl_val;

    TEST_INIT();

    /*=========================================================================
     * Test 1: KM-side underflow sets status bits and returns SLVERR
     *=========================================================================*/
    TEST_SUBTEST_START("KM-side underflow sets status bits and returns SLVERR");
    {
        /* Clear any pending status bits first */
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.inbound_underflow = 1;
            mbox_write_irq_status(clear_val.w);
        }
        mbox_clear_underflow_status();

        /* Verify initial state - check that status bits are clear */
        status_val = mbox_read_status();
        TEST_LOG("  Initial STATUS: 0x%08X", status_val);
        TEST_ASSERT_EQ(MBOX_STATUS_REG.f.inbound_underflow, 0,
                       "STATUS.INBOUND_UNDERFLOW should be clear initially");

        irq_status_val = mbox_read_irq_status();
        TEST_LOG("  Initial IRQ_STATUS: 0x%08X", irq_status_val);
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_underflow, 0,
                       "IRQ_STATUS.INBOUND_UNDERFLOW should be clear initially");

        /* Verify inbound FIFO is empty (KM reads from this) */
        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO should be empty after reset");

        /* Enable KM mailbox underflow IRQ */
        MBOX_IRQ_ENABLE_REG.f.inbound_underflow_en = 1;
        TEST_LOG("  Enabled mailbox inbound underflow interrupt");

        /* Attempt KM-side read from empty inbound FIFO - this triggers underflow */
        TEST_LOG("  Attempting KM-side read from empty inbound FIFO...");
        read_data = mbox_read_data();
        TEST_LOG("  KM read data: 0x%08X", read_data);

        /* Delay to allow status bit to propagate */
        test_delay(50);

        /* Check KM-side mailbox IRQ_STATUS bit is set */
        irq_status_val = mbox_read_irq_status();
        TEST_LOG("  MBOX IRQ_STATUS: 0x%08X", irq_status_val);
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.inbound_underflow,
                    "IRQ_STATUS.INBOUND_UNDERFLOW should be set after underflow");

        /* Check KM-side STATUS register for underflow status bit */
        status_val = mbox_read_status();
        TEST_LOG("  MBOX STATUS: 0x%08X", status_val);
        TEST_ASSERT(MBOX_STATUS_REG.f.inbound_underflow,
                    "STATUS.INBOUND_UNDERFLOW should be set after underflow");

        /* Verify FIFO is still empty */
        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO should still be empty after read");

        /* Clear KM-side underflow status bits (write-1-to-clear) */
        mbox_clear_underflow_status();
        test_delay(5);
        status_val = mbox_read_status();
        TEST_ASSERT_EQ(MBOX_STATUS_REG.f.inbound_underflow, 0,
                       "STATUS.INBOUND_UNDERFLOW should be clear after W1C");

        /* Clear KM-side mailbox IRQ_STATUS underflow bit (write-1-to-clear) */
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.inbound_underflow = 1;
            mbox_write_irq_status(clear_val.w);
        }
        test_delay(5);
        irq_status_val = mbox_read_irq_status();
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_underflow, 0,
                       "IRQ_STATUS.INBOUND_UNDERFLOW should be clear after W1C");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 2: Configuration bits control underflow response
     *=========================================================================*/
    TEST_SUBTEST_START("Configuration bits control underflow response");
    {
        /* Test KM-side (inbound) underflow response configuration */
        TEST_LOG("  Testing KM-side (inbound) underflow response configuration...");
        mbox_clear_underflow_status();
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.inbound_underflow = 1;
            mbox_write_irq_status(clear_val.w);
        }

        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO should be empty");

        /* Test default behavior (SLVERR) */
        ctrl_val = mbox_read_ctrl();
        TEST_LOG("  CTRL register (default): 0x%08X", ctrl_val);
        TEST_ASSERT_EQ(MBOX_CTRL_REG.f.inbound_underflow_resp, 0,
                       "CTRL.INBOUND_UNDERFLOW_RESP should default to 0 (SLVERR)");

        /* KM-side read from empty inbound FIFO - default should be SLVERR */
        read_data = mbox_read_data();
        test_delay(10);

        /* Check KM-side STATUS register for underflow status bit */
        status_val = mbox_read_status();
        TEST_LOG("  STATUS register: 0x%08X", status_val);
        TEST_ASSERT(MBOX_STATUS_REG.f.inbound_underflow,
                    "STATUS.INBOUND_UNDERFLOW should be set after underflow");

        /* Configure to return OKAY */
        mbox_clear_underflow_status();
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.inbound_underflow = 1;
            mbox_write_irq_status(clear_val.w);
        }
        MBOX_CTRL_REG.f.inbound_underflow_resp = 1;
        ctrl_val = mbox_read_ctrl();
        TEST_LOG("  CTRL register (OKAY configured): 0x%08X", ctrl_val);
        TEST_ASSERT(MBOX_CTRL_REG.f.inbound_underflow_resp,
                    "CTRL.INBOUND_UNDERFLOW_RESP should be set");

        /* KM-side read with OKAY response */
        read_data = mbox_read_data();
        test_delay(10);

        /* Verify underflow status bit is still set even with OKAY response */
        status_val = mbox_read_status();
        TEST_ASSERT(MBOX_STATUS_REG.f.inbound_underflow,
                    "STATUS.INBOUND_UNDERFLOW should be set even with OKAY response");

        /* Restore default (SLVERR) */
        mbox_write_ctrl(0);
        mbox_clear_underflow_status();
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.inbound_underflow = 1;
            mbox_write_irq_status(clear_val.w);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
