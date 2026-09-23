/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_km_to_sep.c
 * @brief Mailbox KM->SEP message test (firmware-driven)
 *
 * Verifies that KM CPU can send messages to SEP host via mailbox and SEP receives IRQ.
 *
 * Tests:
 * - SEP enables its IRQ via IRQ_ENABLE register (via testbench command)
 * - KM writes message to mailbox outbound FIFO (via KM mailbox WRITE_DATA)
 * - Mailbox asserts mbox_irq_to_sep output when FIFO becomes non-empty
 * - SEP reads message from outbound FIFO (via testbench command)
 * - IRQ is level-sensitive (deasserts when FIFO becomes empty)
 * - Multiple message sequence
 * - IRQ enable gating
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_km_to_sep
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "km_mailbox_sep_regs.h"

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

/* Helper to construct IRQ_ENABLE value for SEP mailbox from struct field.
 * NOTE: KM_MAILBOX_SEP_* types are ONLY for constructing bit patterns to pass
 * to testbench commands. SEP mailbox registers are NOT accessible from KM and
 * must be accessed via testbench command interface (tb_sep_mbox_* functions).
 */
static inline uint32_t sep_mbox_irq_enable_outbound_read_data_avail(void) {
    KM_MAILBOX_SEP_IRQ_ENABLE_REG_reg_u enable_val = {0};
    enable_val.f.outbound_read_data_avail_en = 1;
    return enable_val.w;
}

/* Test patterns */
#define TEST_MESSAGE_1 0xCAFEBABE
#define TEST_MESSAGE_2 0xDEADBEEF
#define TEST_MESSAGE_3 0x12345678
#define TEST_MESSAGE_4 0xA5A5A5A5

/**
 * Read mailbox STATUS register.
 */
static inline uint32_t mbox_read_status(void) {
    return MBOX_STATUS_REG.w;
}

/**
 * Write mailbox WRITE_DATA register (writes to outbound FIFO).
 */
static inline void mbox_write_data(uint32_t value) {
    MBOX_WRITE_DATA_REG.w = value;
}

/**
 * Check if outbound FIFO is empty.
 */
static inline int mbox_outbound_empty(void) {
    return MBOX_STATUS_REG.f.outbound_empty != 0;
}

/**
 * Check if outbound FIFO is full.
 */
static inline int mbox_outbound_full(void) {
    return MBOX_STATUS_REG.f.outbound_full != 0;
}

/**
 * Wait for outbound FIFO to become non-empty (with timeout).
 */
static inline int mbox_wait_for_outbound_data(uint32_t timeout_cycles) {
    for (uint32_t i = 0; i < timeout_cycles; i++) {
        if (!mbox_outbound_empty()) {
            return 1; /* Data available */
        }
        test_delay(1);
    }
    return 0; /* Timeout */
}

int main(void) {
    uint32_t read_data;
    uint32_t sep_irq_status;

    TEST_INIT();

    if (!tb_set_timeout(800000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /*=========================================================================
     * Test 1: Verify mailbox outbound FIFO empty by default
     *=========================================================================*/
    TEST_SUBTEST_START("Mailbox outbound FIFO empty by default");
    {
        /* Check outbound FIFO is empty */
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO empty after reset");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 2: Enable SEP IRQ and write message from KM
     *=========================================================================*/
    TEST_SUBTEST_START("Enable SEP IRQ and write message");
    {
        /* Request testbench to enable SEP mailbox IRQ */
        TEST_LOG("  Requesting testbench to enable SEP mailbox IRQ");
        if (!tb_sep_mbox_irq_enable(sep_mbox_irq_enable_outbound_read_data_avail(), 1000)) {
            TEST_FAIL("Failed to enable SEP mailbox IRQ");
        }

        /* Write message to outbound FIFO */
        TEST_LOG("  Writing 0x%08X to mailbox outbound FIFO", TEST_MESSAGE_1);
        mbox_write_data(TEST_MESSAGE_1);
        test_delay(20); /* Wait for FIFO to update */

        /* Verify outbound FIFO is non-empty */
        TEST_ASSERT(!mbox_outbound_empty(), "Outbound FIFO non-empty after write");

        /* Check SEP IRQ is asserted (via testbench) */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ status");
        }
        TEST_LOG("  SEP IRQ status: 0x%08X", sep_irq_status);
        TEST_ASSERT_EQ(sep_irq_status, 1, "SEP IRQ asserted");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 3: SEP reads message from outbound FIFO
     *=========================================================================*/
    TEST_SUBTEST_START("SEP reads message from outbound FIFO");
    {
        /* Request testbench to read from SEP mailbox */
        TEST_LOG("  Requesting testbench to read from SEP mailbox");
        if (!tb_sep_mbox_read(&read_data, 1000)) {
            TEST_FAIL("Failed to read from SEP mailbox");
        }

        TEST_LOG("  Read data: 0x%08X", read_data);
        TEST_ASSERT_EQ(read_data, TEST_MESSAGE_1, "Message read correctly");

        /* Wait for FIFO to update */
        test_delay(10);

        /* Verify FIFO is empty after read */
        TEST_ASSERT(mbox_outbound_empty(), "FIFO empty after read");

        /* Check SEP IRQ is deasserted */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ status");
        }
        TEST_ASSERT_EQ(sep_irq_status, 0, "SEP IRQ deasserted when FIFO empty");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 4: Multiple message sequence (FIFO order)
     *=========================================================================*/
    TEST_SUBTEST_START("Multiple message sequence");
    {
        uint32_t test_messages[4] = {TEST_MESSAGE_1, TEST_MESSAGE_2, TEST_MESSAGE_3,
                                     TEST_MESSAGE_4};

        /* Write 4 messages to outbound FIFO */
        TEST_LOG("  Writing 4 messages to mailbox outbound FIFO...");
        for (unsigned i = 0; i < 4; i++) {
            mbox_write_data(test_messages[i]);
            test_delay(5); /* Small delay between writes */
        }

        /* Wait for FIFO to update */
        test_delay(20);

        /* Read back in FIFO order */
        TEST_LOG("  Reading messages in FIFO order...");
        for (unsigned i = 0; i < 4; i++) {
            if (!tb_sep_mbox_read(&read_data, 1000)) {
                TEST_FAIL("Failed to read message %u", i);
            }
            TEST_LOG("    Message %u: expected 0x%08X, got 0x%08X", i, test_messages[i], read_data);
            TEST_ASSERT_EQ(read_data, test_messages[i], "Message order correct");
            test_delay(5);
        }

        /* Verify FIFO is empty */
        TEST_ASSERT(mbox_outbound_empty(), "FIFO empty after reading all messages");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 5: IRQ enable gating - IRQ disabled, data written, no IRQ
     *=========================================================================*/
    TEST_SUBTEST_START("IRQ enable gating");
    {
        /* Disable SEP mailbox IRQ */
        TEST_LOG("  Disabling SEP mailbox IRQ");
        if (!tb_sep_mbox_irq_enable(0, 1000)) {
            TEST_FAIL("Failed to disable SEP mailbox IRQ");
        }

        /* Write message */
        mbox_write_data(TEST_MESSAGE_2);
        test_delay(20);

        /* Verify outbound FIFO has data */
        TEST_ASSERT(!mbox_outbound_empty(), "Outbound FIFO has data");

        /* Check SEP IRQ should not be asserted (IRQ disabled) */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ status");
        }
        TEST_LOG("  SEP IRQ status (IRQ disabled): 0x%08X", sep_irq_status);
        TEST_ASSERT_EQ(sep_irq_status, 0, "SEP IRQ not asserted when IRQ disabled");

        /* Re-enable IRQ */
        TEST_LOG("  Re-enabling SEP mailbox IRQ");
        if (!tb_sep_mbox_irq_enable(sep_mbox_irq_enable_outbound_read_data_avail(), 1000)) {
            TEST_FAIL("Failed to re-enable SEP mailbox IRQ");
        }

        /* Now SEP IRQ should be asserted */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ status");
        }
        TEST_ASSERT_EQ(sep_irq_status, 1, "SEP IRQ asserted after enabling IRQ");

        /* Read the message */
        if (!tb_sep_mbox_read(&read_data, 1000)) {
            TEST_FAIL("Failed to read message");
        }
        TEST_ASSERT_EQ(read_data, TEST_MESSAGE_2, "Message read correctly");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 6: Partial drain - write multiple, read some, verify IRQ behavior
     *=========================================================================*/
    TEST_SUBTEST_START("Partial drain - IRQ behavior");
    {
        /* Write 3 messages */
        for (unsigned i = 0; i < 3; i++) {
            mbox_write_data(TEST_MESSAGE_1 + i);
            test_delay(5);
        }

        test_delay(20);

        /* Read only 2 messages */
        for (unsigned i = 0; i < 2; i++) {
            if (!tb_sep_mbox_read(&read_data, 1000)) {
                TEST_FAIL("Failed to read message %u", i);
            }
            TEST_ASSERT_EQ(read_data, TEST_MESSAGE_1 + i, "Partial read");
        }

        /* Verify FIFO still has data */
        test_delay(10);
        TEST_ASSERT(!mbox_outbound_empty(), "FIFO not empty after partial drain");

        /* SEP IRQ should still be asserted */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ status");
        }
        TEST_ASSERT_EQ(sep_irq_status, 1, "SEP IRQ still asserted with data in FIFO");

        /* Read remaining message */
        if (!tb_sep_mbox_read(&read_data, 1000)) {
            TEST_FAIL("Failed to read final message");
        }
        TEST_ASSERT_EQ(read_data, TEST_MESSAGE_1 + 2, "Final message");

        /* Verify FIFO empty and IRQ cleared */
        test_delay(10);
        TEST_ASSERT(mbox_outbound_empty(), "FIFO empty after full drain");

        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ status");
        }
        TEST_ASSERT_EQ(sep_irq_status, 0, "SEP IRQ deasserted when FIFO empty");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 7: KM outbound write-FIFO space IRQ - level-sensitive behavior
     *
     * Verifies OUTBOUND_WRITE_SPACE_AVAIL (IRQ_STATUS bit 1) and
     * OUTBOUND_WRITE_SPACE_AVAIL_EN (IRQ_ENABLE bit 1).
     * The interrupt is level-sensitive: asserted while the outbound FIFO
     * has at least one free slot, deasserted when full.
     *=========================================================================*/
    TEST_SUBTEST_START("KM outbound write-FIFO space IRQ - basic level behavior");
    {
        uint32_t irq_status_val;

        /* Ensure outbound FIFO is empty (drained by earlier tests) */
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO should be empty");

        /* outbound_write_space_avail should be 1 (FIFO has space) even before enable */
        irq_status_val = MBOX_IRQ_STATUS_REG.w;
        TEST_LOG("  KM IRQ_STATUS (before enable): 0x%08X", irq_status_val);
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "IRQ_STATUS.outbound_write_space_avail should be set when FIFO has space");

        /* Enable the outbound write space IRQ */
        MBOX_IRQ_ENABLE_REG.f.outbound_write_space_avail_en = 1;
        test_delay(10);
        TEST_ASSERT(MBOX_IRQ_ENABLE_REG.f.outbound_write_space_avail_en,
                    "IRQ_ENABLE.outbound_write_space_avail_en should be set");

        /* Fill outbound FIFO to capacity (MAILBOX_DEPTH = 16) */
        TEST_LOG("  Filling outbound FIFO with %d entries...", 16);
        for (unsigned i = 0; i < 16; i++) {
            mbox_write_data(0xA000 + i);
            test_delay(5);
        }
        test_delay(10);

        /* FIFO is full: outbound_write_space_avail should be 0, IRQ should be deasserted */
        TEST_ASSERT(mbox_outbound_full(), "Outbound FIFO should be full");
        irq_status_val = MBOX_IRQ_STATUS_REG.w;
        TEST_LOG("  KM IRQ_STATUS (FIFO full): 0x%08X", irq_status_val);
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail, 0,
                       "IRQ_STATUS.outbound_write_space_avail should be clear when FIFO full");

        /* SEP reads one entry -> FIFO has space again */
        if (!tb_sep_mbox_read(&read_data, 1000)) {
            TEST_FAIL("Failed to read from SEP mailbox");
        }
        test_delay(10);

        /* outbound_write_space_avail should be 1 again (space available) */
        irq_status_val = MBOX_IRQ_STATUS_REG.w;
        TEST_LOG("  KM IRQ_STATUS (after one SEP read): 0x%08X", irq_status_val);
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "IRQ_STATUS.outbound_write_space_avail should be set after SEP reads one entry");

        /* Drain remaining entries */
        for (unsigned i = 1; i < 16; i++) {
            if (!tb_sep_mbox_read(&read_data, 1000)) {
                TEST_FAIL("Failed to drain entry %u", i);
            }
        }
        test_delay(10);
        TEST_ASSERT(mbox_outbound_empty(), "Outbound FIFO should be empty after drain");

        /* outbound_write_space_avail still set (empty FIFO has space) */
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "IRQ_STATUS.outbound_write_space_avail should be set when FIFO is empty (has space)");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 8: KM outbound write-FIFO space IRQ - enable gating
     *
     * Status bit should always reflect FIFO state regardless of enable;
     * enable only gates the IRQ line.
     *=========================================================================*/
    TEST_SUBTEST_START("KM outbound write-FIFO space IRQ - enable gating");
    {
        uint32_t irq_status_val;

        /* Disable the write-space IRQ */
        MBOX_IRQ_ENABLE_REG.f.outbound_write_space_avail_en = 0;
        test_delay(10);

        /* outbound_write_space_avail should still reflect FIFO state (has space) */
        irq_status_val = MBOX_IRQ_STATUS_REG.w;
        TEST_LOG("  KM IRQ_STATUS (IRQ disabled, FIFO has space): 0x%08X", irq_status_val);
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "Status bit reflects FIFO state even when IRQ disabled");

        /* Fill FIFO to full */
        for (unsigned i = 0; i < 16; i++) {
            mbox_write_data(0xB000 + i);
            test_delay(5);
        }
        test_delay(10);

        /* outbound_write_space_avail should be 0 (FIFO full), IRQ still disabled */
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail, 0,
                       "Status bit clear when FIFO full (IRQ disabled)");

        /* Drain one entry */
        if (!tb_sep_mbox_read(&read_data, 1000)) {
            TEST_FAIL("Failed to read from SEP mailbox");
        }
        test_delay(10);

        /* outbound_write_space_avail should be 1 (space available), but IRQ not asserted */
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "Status bit set when FIFO has space (IRQ still disabled)");

        /* Drain remaining */
        for (unsigned i = 1; i < 16; i++) {
            if (!tb_sep_mbox_read(&read_data, 1000)) {
                TEST_FAIL("Failed to drain entry %u", i);
            }
        }
        test_delay(10);

        /* Clean up: disable write-space IRQ, disable all other IRQs */
        MBOX_IRQ_ENABLE_REG.w = 0;
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 9: KM outbound write-FIFO space IRQ - fill/empty cycle
     *
     * Fill FIFO completely, verify IRQ deasserts, then consumer reads all;
     * verify IRQ reasserts.
     *=========================================================================*/
    TEST_SUBTEST_START("KM outbound write-FIFO space IRQ - fill/empty cycle");
    {
        /* Enable only the write-space IRQ */
        MBOX_IRQ_ENABLE_REG.w = 0;
        MBOX_IRQ_ENABLE_REG.f.outbound_write_space_avail_en = 1;
        test_delay(10);

        /* FIFO is empty -> outbound_write_space_avail should be 1 */
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "Status bit set when FIFO empty (has space)");

        /* Fill FIFO to full */
        for (unsigned i = 0; i < 16; i++) {
            mbox_write_data(0xC000 + i);
            test_delay(5);
        }
        test_delay(10);

        /* FIFO full -> outbound_write_space_avail should be 0 */
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail, 0,
                       "Status bit clear when FIFO full");

        /* Drain all entries */
        for (unsigned i = 0; i < 16; i++) {
            if (!tb_sep_mbox_read(&read_data, 1000)) {
                TEST_FAIL("Failed to drain entry %u", i);
            }
        }
        test_delay(10);

        /* FIFO empty again -> outbound_write_space_avail should be 1 */
        TEST_ASSERT(MBOX_IRQ_STATUS_REG.f.outbound_write_space_avail,
                    "Status bit reasserts after FIFO drained");

        /* Clean up */
        MBOX_IRQ_ENABLE_REG.w = 0;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
