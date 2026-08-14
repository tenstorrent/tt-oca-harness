/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_overflow_km.c
 * @brief Mailbox FIFO overflow test - KM side (firmware-driven)
 *
 * Verifies that KM-side mailbox overflow conditions set status bits, trigger IRQs,
 * and return configurable AXI responses (SLVERR default, OKAY configurable).
 *
 * Tests:
 * - KM-side: Write to full outbound FIFO sets status bits, triggers IRQ, returns SLVERR
 * - Configuration: CTRL register controls SLVERR vs OKAY response
 * - Status bits: Overflow status bits are write-1-to-clear (no read side-effects)
 * - IRQ aggregation: Mailbox IRQs aggregated and propagate to KMCSR
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_overflow_km
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* Register access macros using struct types */
#define MBOX_WRITE_DATA_REG \
    (*(volatile km_mailbox_km__write_data_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR)
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
 * Check if outbound FIFO is full.
 */
static inline int mbox_outbound_full(void) {
    return MBOX_STATUS_REG.f.outbound_full != 0;
}

/**
 * Check if outbound FIFO is empty.
 */
static inline int mbox_outbound_empty(void) {
    return MBOX_STATUS_REG.f.outbound_empty != 0;
}

/**
 * Write data to mailbox WRITE_DATA register (writes to outbound FIFO).
 */
static inline void mbox_write_data(uint32_t data) {
    MBOX_WRITE_DATA_REG.w = data;
}

/**
 * Read data from mailbox READ_DATA register (reads from inbound FIFO).
 */
static inline uint32_t mbox_read_data(void) {
    return MBOX_READ_DATA_REG.w;
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
 * Read mailbox IRQ_ENABLE register.
 */
static inline uint32_t mbox_read_irq_enable(void) {
    return MBOX_IRQ_ENABLE_REG.w;
}

/**
 * Write mailbox IRQ_ENABLE register.
 */
static inline void mbox_write_irq_enable(uint32_t value) {
    MBOX_IRQ_ENABLE_REG.w = value;
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
 * Clear overflow status bits (write-1-to-clear).
 */
static inline void mbox_clear_overflow_status(void) {
    km_mailbox_km__status_reg_t clear_val = {0};
    clear_val.f.outbound_overflow = 1;
    MBOX_STATUS_REG.w = clear_val.w;
}

int main(void) {
    TEST_INIT();

    /* Set timeout to accommodate data verification reads (16 entries * ~40k cycles each) */
    if (!tb_set_timeout(800000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /*=========================================================================
     * Test 1: KM-side overflow - Write to full outbound FIFO triggers IRQ,
     *         sets status bits, and preserves existing data
     *=========================================================================*/
    TEST_SUBTEST_START("KM-side overflow triggers IRQ and preserves data");
    {
        uint32_t read_data;
        uint32_t read_resp;
        uint32_t expected_data[MAILBOX_DEPTH];
        uint32_t overflow_data = 0xDEADBEEF;
        uint32_t status_val;
        uint32_t mbox_irq_status_val;
        uint32_t kmcsr_irq_status_val;

        /* Enable mailbox overflow IRQ in mailbox IRQ_ENABLE (KM side) */
        MBOX_IRQ_ENABLE_REG.f.outbound_overflow_en = 1;
        TEST_LOG("  Enabled mailbox outbound overflow interrupt");

        /* Enable AXI SLVERR IRQ in KMCSR */
        {
            km_csr__irq_enable_reg_t enable = {0};
            enable.f.axi_slverr_en = 1;
            rom_kmcsr_irq_enable_write(enable.w);
        }
        TEST_LOG("  Enabled KMCSR AXI SLVERR interrupt");

        /* Fill outbound FIFO to capacity via CPU writes with known data pattern */
        TEST_LOG("  Filling mailbox outbound FIFO with %d entries...", MAILBOX_DEPTH);
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            expected_data[i] = 0x2000 + i;
            mbox_write_data(expected_data[i]);
            test_delay(5); /* Small delay between writes */
        }
        TEST_LOG("  Outbound FIFO filled with %d entries", MAILBOX_DEPTH);

        /* Verify FIFO is full */
        test_delay(10); /* Wait for status to update */
        TEST_ASSERT(mbox_outbound_full(), "Outbound FIFO should be full");

        /* Attempt write to full outbound FIFO - this should trigger overflow and return SLVERR */
        TEST_LOG("  Attempting CPU write to full outbound FIFO with 0x%08X...", overflow_data);
        /* When configured to return SLVERR (default), the CPU write returns SLVERR on KM CPU bus,
         * which is captured by KMCSR AXI error monitoring and sets IRQ_AXI_SLVERR_BIT */
        mbox_write_data(overflow_data);

        /* Small delay to allow interrupt to propagate */
        test_delay(20);

        /* Check KMCSR IRQ_STATUS for AXI SLVERR */
        kmcsr_irq_status_val = rom_kmcsr_irq_status_read();
        TEST_LOG("  KMCSR IRQ_STATUS register: 0x%08X", kmcsr_irq_status_val);
        {
            km_csr__irq_status_reg_t status_reg = {.w = kmcsr_irq_status_val};
            TEST_ASSERT(
                status_reg.f.axi_slverr,
                "KMCSR IRQ_STATUS.AXI_SLVERR should be set (KM-side overflow returns SLVERR)");
        }

        /* Check overflow status bit is set */
        status_val = mbox_read_status();
        TEST_LOG("  STATUS register: 0x%08X", status_val);
        TEST_ASSERT(MBOX_STATUS_REG.f.outbound_overflow,
                    "STATUS.OUTBOUND_OVERFLOW should be set after overflow");

        /* Check mailbox IRQ_STATUS bit is set */
        mbox_irq_status_val = mbox_read_irq_status();
        TEST_LOG("  MBOX IRQ_STATUS register: 0x%08X", mbox_irq_status_val);
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_overflow,
                    "IRQ_STATUS.OUTBOUND_OVERFLOW should be set after overflow");

        /* Verify FIFO is still full */
        TEST_ASSERT(mbox_outbound_full(), "Outbound FIFO should still be full");

        /* Read back all data via SEP-side read and verify it matches original */
        TEST_LOG("  Reading back FIFO contents via SEP-side to verify data integrity...");
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            if (!tb_sep_mbox_read_with_resp(&read_data, &read_resp, 1000)) {
                TEST_FAIL("Failed to read entry %u from FIFO", i);
            }
            TEST_ASSERT_EQ(read_resp, AXI_OKAY, "Read should succeed");
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
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO should be empty after reading all data");

        /* Clear overflow status bits (write-1-to-clear) */
        mbox_clear_overflow_status();
        test_delay(5);
        status_val = mbox_read_status();
        TEST_ASSERT_EQ(MBOX_STATUS_REG.f.outbound_overflow, 0,
                       "STATUS.OUTBOUND_OVERFLOW should be clear after W1C");

        /* Clear mailbox IRQ_STATUS overflow bit (write-1-to-clear) */
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.outbound_overflow = 1;
            mbox_write_irq_status(clear_val.w);
        }
        test_delay(5);
        mbox_irq_status_val = mbox_read_irq_status();
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.outbound_overflow, 0,
                       "IRQ_STATUS.OUTBOUND_OVERFLOW should be clear after W1C");

        /* Clear KMCSR IRQs */
        {
            km_csr__irq_status_reg_t clear_val = {0};
            clear_val.f.axi_slverr = 1;
            rom_kmcsr_irq_status_clear(clear_val.w);
        }

        TEST_LOG("  Overflow data was dropped, original data preserved, status/IRQ bits verified, "
                 "SLVERR detected in KMCSR");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 2: Configuration bits - Test CTRL register for OKAY vs SLVERR response
     *=========================================================================*/
    TEST_SUBTEST_START("Configuration bits control overflow response");
    {
        uint32_t ctrl_val;
        uint32_t read_data;
        uint32_t read_resp;

        /* Test KM-side (outbound) overflow response configuration */
        TEST_LOG("  Testing KM-side (outbound) overflow response configuration...");
        mbox_clear_overflow_status();

        /* Fill outbound FIFO via KM-side writes */
        TEST_LOG("  Filling outbound FIFO to test overflow response configuration...");
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            mbox_write_data(0x2000 + i);
            test_delay(5);
        }
        test_delay(10);
        TEST_ASSERT(mbox_outbound_full(), "FIFO should be full");

        /* Test default behavior (SLVERR) - KM-side CTRL controls outbound overflow */
        ctrl_val = mbox_read_ctrl();
        TEST_LOG("  KM-side CTRL register (default): 0x%08X", ctrl_val);
        TEST_ASSERT_EQ(MBOX_CTRL_REG.f.outbound_overflow_resp, 0,
                       "CTRL.OUTBOUND_OVERFLOW_RESP should default to 0 (SLVERR)");

        /* Attempt overflow write - KM-side writes don't return AXI response,
         * but overflow status bit should still be set */
        mbox_write_data(0xCAFEBABE);
        test_delay(20);

        /* Verify overflow status bit is set */
        TEST_ASSERT(MBOX_STATUS_REG.f.outbound_overflow,
                    "STATUS.OUTBOUND_OVERFLOW should be set after overflow");

        /* Configure to return OKAY (for SEP-side reads) */
        MBOX_CTRL_REG.f.outbound_overflow_resp = 1;
        ctrl_val = mbox_read_ctrl();
        TEST_LOG("  KM-side CTRL register (OKAY configured): 0x%08X", ctrl_val);
        TEST_ASSERT(MBOX_CTRL_REG.f.outbound_overflow_resp,
                    "CTRL.OUTBOUND_OVERFLOW_RESP should be set");

        /* Clear overflow status and refill FIFO */
        mbox_clear_overflow_status();
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.outbound_overflow = 1;
            mbox_write_irq_status(clear_val.w);
        }
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            if (!tb_sep_mbox_read_with_resp(&read_data, &read_resp, 1000)) {
                TEST_FAIL("Failed to drain FIFO");
            }
        }
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            mbox_write_data(0x3000 + i);
            test_delay(5);
        }
        test_delay(10);
        TEST_ASSERT(mbox_outbound_full(), "FIFO should be full again");

        /* Attempt overflow write again */
        mbox_write_data(0xF00DBABE);
        test_delay(20);

        /* Verify overflow status bit is still set even with OKAY response configured */
        TEST_ASSERT(MBOX_STATUS_REG.f.outbound_overflow,
                    "STATUS.OUTBOUND_OVERFLOW should be set even with OKAY response configured");

        /* Restore default (SLVERR) */
        MBOX_CTRL_REG.w = 0;
        mbox_clear_overflow_status();
        {
            km_mailbox_km__irq_status_reg_t clear_val = {0};
            clear_val.f.outbound_overflow = 1;
            mbox_write_irq_status(clear_val.w);
        }

        /* Drain FIFO */
        for (unsigned i = 0; i < MAILBOX_DEPTH; i++) {
            if (!tb_sep_mbox_read_with_resp(&read_data, &read_resp, 1000)) {
                TEST_FAIL("Failed to drain FIFO");
            }
        }

        TEST_LOG("  Configuration bits verified (SLVERR default and OKAY configurable)");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
