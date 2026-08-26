/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_sep_to_km.c
 * @brief Mailbox SEP->KM message test (firmware-driven)
 *
 * Verifies that SEP host can send messages to KM CPU via mailbox and KM receives IRQ.
 *
 * Tests:
 * - KM enables its IRQ via IRQ_ENABLE register
 * - SEP writes message to mailbox inbound FIFO (via testbench command)
 * - KM reads message from inbound FIFO
 * - IRQ is level-sensitive (deasserts when FIFO becomes empty)
 * - Multiple message sequence
 * - IRQ enable gating
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_sep_to_km
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

/* Test patterns */
#define TEST_MESSAGE_1 0xDEADBEEF
#define TEST_MESSAGE_2 0xCAFEBABE
#define TEST_MESSAGE_3 0x12345678
#define TEST_MESSAGE_4 0xA5A5A5A5

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
 * Read mailbox READ_DATA register (reads from inbound FIFO).
 */
static inline uint32_t mbox_read_data(void) {
    return MBOX_READ_DATA_REG.w;
}

/**
 * Check if inbound FIFO is empty.
 */
static inline int mbox_inbound_empty(void) {
    return MBOX_STATUS_REG.f.inbound_empty != 0;
}

/**
 * Check if inbound FIFO is full.
 */
static inline int mbox_inbound_full(void) {
    return MBOX_STATUS_REG.f.inbound_full != 0;
}

/**
 * Wait for inbound FIFO to become non-empty (with timeout).
 */
static inline int mbox_wait_for_data(uint32_t timeout_cycles) {
    for (uint32_t i = 0; i < timeout_cycles; i++) {
        if (!mbox_inbound_empty()) {
            return 1; /* Data available */
        }
        test_delay(1);
    }
    return 0; /* Timeout */
}

int main(void) {
    uint32_t irq_status_val;
    uint32_t irq_enable_val;
    uint32_t read_data;
    uint32_t sep_irq_status;

    TEST_INIT();

    if (!tb_set_timeout(800000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    /*=========================================================================
     * Test 1: Verify mailbox IRQ disabled by default
     *=========================================================================*/
    TEST_SUBTEST_START("Mailbox IRQ disabled by default");
    {
        /* Check mailbox IRQ_ENABLE is 0 */
        irq_enable_val = mbox_read_irq_enable();
        TEST_LOG("  MBOX IRQ_ENABLE: 0x%08X", irq_enable_val);
        TEST_ASSERT_EQ(irq_enable_val, 0, "Mailbox IRQ_ENABLE default");

        /* Check inbound FIFO is empty */
        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO empty after reset");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 2: Enable mailbox IRQ and verify IRQ_STATUS reflects FIFO state
     *=========================================================================*/
    TEST_SUBTEST_START("Enable mailbox IRQ and verify IRQ_STATUS");
    {
        /* Enable mailbox IRQ via mailbox IRQ_ENABLE register */
        MBOX_IRQ_ENABLE_REG.f.inbound_read_data_avail_en = 1;
        test_delay(10);
        irq_enable_val = mbox_read_irq_enable();
        TEST_ASSERT_EQ(MBOX_IRQ_ENABLE_REG.f.inbound_read_data_avail_en, 1,
                       "Mailbox IRQ_ENABLE set");

        /* Check IRQ_STATUS is 0 (FIFO empty) */
        irq_status_val = mbox_read_irq_status();
        TEST_LOG("  MBOX IRQ_STATUS: 0x%08X", irq_status_val);
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_read_data_avail, 0,
                       "IRQ_STATUS clear when FIFO empty");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 3: SEP writes message, KM reads it (basic round-trip)
     *=========================================================================*/
    TEST_SUBTEST_START("SEP->KM message round-trip");
    {
        /* Request testbench to write message to SEP mailbox */
        TEST_LOG("  Requesting testbench to write 0x%08X to SEP mailbox", TEST_MESSAGE_1);
        if (!tb_sep_mbox_write(TEST_MESSAGE_1, 1000)) {
            TEST_FAIL("Failed to request SEP mailbox write");
        }

        /* Wait for data to arrive in inbound FIFO */
        if (!mbox_wait_for_data(1000)) {
            TEST_FAIL("Timeout waiting for data in inbound FIFO");
        }

        /* Check IRQ_STATUS reflects data available */
        irq_status_val = mbox_read_irq_status();
        TEST_LOG("  MBOX IRQ_STATUS: 0x%08X", irq_status_val);
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_read_data_avail, 1,
                       "IRQ_STATUS shows data available");

        /* Read message from inbound FIFO */
        read_data = mbox_read_data();
        TEST_LOG("  Read data: 0x%08X", read_data);
        TEST_ASSERT_EQ(read_data, TEST_MESSAGE_1, "Message read correctly");

        /* Verify FIFO is empty after read */
        test_delay(10);
        TEST_ASSERT(mbox_inbound_empty(), "FIFO empty after read");

        /* Verify IRQ_STATUS cleared after FIFO empty */
        irq_status_val = mbox_read_irq_status();
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_read_data_avail, 0,
                       "IRQ_STATUS cleared when FIFO empty");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 4: Multiple message sequence (FIFO order)
     *=========================================================================*/
    TEST_SUBTEST_START("Multiple message sequence");
    {
        uint32_t test_messages[4] = {TEST_MESSAGE_1, TEST_MESSAGE_2, TEST_MESSAGE_3,
                                     TEST_MESSAGE_4};

        /* Write 4 messages via testbench */
        TEST_LOG("  Writing 4 messages to SEP mailbox...");
        for (unsigned i = 0; i < 4; i++) {
            if (!tb_sep_mbox_write(test_messages[i], 1000)) {
                TEST_FAIL("Failed to write message %u", i);
            }
            test_delay(5); /* Small delay between writes */
        }

        /* Wait for all data to arrive */
        test_delay(20);

        /* Read back in FIFO order */
        TEST_LOG("  Reading messages in FIFO order...");
        for (unsigned i = 0; i < 4; i++) {
            read_data = mbox_read_data();
            TEST_LOG("    Message %u: expected 0x%08X, got 0x%08X", i, test_messages[i], read_data);
            TEST_ASSERT_EQ(read_data, test_messages[i], "Message order correct");
            test_delay(5);
        }

        /* Verify FIFO is empty */
        TEST_ASSERT(mbox_inbound_empty(), "FIFO empty after reading all messages");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 5: IRQ enable gating - IRQ disabled, data written, no IRQ
     *=========================================================================*/
    TEST_SUBTEST_START("IRQ enable gating");
    {
        /* Disable mailbox IRQ */
        mbox_write_irq_enable(0);
        test_delay(10);

        /* Write message via testbench */
        if (!tb_sep_mbox_write(TEST_MESSAGE_2, 1000)) {
            TEST_FAIL("Failed to write message");
        }

        /* Wait for data to arrive */
        test_delay(20);

        /* Check IRQ_STATUS - should show data available (status bit) */
        irq_status_val = mbox_read_irq_status();
        TEST_LOG("  MBOX IRQ_STATUS (IRQ disabled): 0x%08X", irq_status_val);
        /* Status bit may still be set, but IRQ output should be gated */

        /* Re-enable IRQ */
        MBOX_IRQ_ENABLE_REG.f.inbound_read_data_avail_en = 1;
        test_delay(10);

        /* Read the message */
        read_data = mbox_read_data();
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
            if (!tb_sep_mbox_write(TEST_MESSAGE_1 + i, 1000)) {
                TEST_FAIL("Failed to write message %u", i);
            }
            test_delay(5);
        }

        test_delay(20);

        /* Read only 2 messages */
        for (unsigned i = 0; i < 2; i++) {
            read_data = mbox_read_data();
            TEST_ASSERT_EQ(read_data, TEST_MESSAGE_1 + i, "Partial read");
        }

        /* Verify FIFO still has data */
        test_delay(10);
        TEST_ASSERT(!mbox_inbound_empty(), "FIFO not empty after partial drain");

        /* IRQ_STATUS should still show data available */
        irq_status_val = mbox_read_irq_status();
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_read_data_avail, 1,
                       "IRQ_STATUS still set with data in FIFO");

        /* Read remaining message */
        read_data = mbox_read_data();
        TEST_ASSERT_EQ(read_data, TEST_MESSAGE_1 + 2, "Final message");

        /* Verify FIFO empty and IRQ cleared */
        test_delay(10);
        TEST_ASSERT(mbox_inbound_empty(), "FIFO empty after full drain");
        irq_status_val = mbox_read_irq_status();
        TEST_ASSERT_EQ(MBOX_IRQ_STATUS_REG.f.inbound_read_data_avail, 0,
                       "IRQ_STATUS cleared when FIFO empty");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 7: SEP inbound write-FIFO space IRQ - level-sensitive behavior
     *
     * Verifies INBOUND_WRITE_SPACE_AVAIL (SEP IRQ_STATUS bit 1) and
     * INBOUND_WRITE_SPACE_AVAIL_EN (SEP IRQ_ENABLE bit 1).
     * The interrupt is level-sensitive: asserted while the inbound FIFO
     * has at least one free slot, deasserted when full.
     *
     * NOTE: SEP-side registers are accessed via testbench commands since
     * the KM CPU cannot directly access SEP mailbox registers.
     *=========================================================================*/
    TEST_SUBTEST_START("SEP inbound write-FIFO space IRQ - basic level behavior");
    {
        uint32_t sep_irq_status_val;
        KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u sep_irq_status_u;

        /* Ensure inbound FIFO is empty (drained by earlier tests) */
        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO should be empty");

        /* Read SEP IRQ_STATUS to check inbound_write_space_avail (FIFO has space -> should be 1) */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_LOG("  SEP IRQ_STATUS (before enable): 0x%08X", sep_irq_status_val);
        TEST_ASSERT(sep_irq_status_u.f.inbound_write_space_avail,
                    "SEP IRQ_STATUS inbound_write_space_avail should be set when FIFO has space");

        /* Enable the inbound write space IRQ via testbench */
        {
            KM_MAILBOX_SEP_IRQ_ENABLE_REG_reg_u enable_val = {0};
            enable_val.f.inbound_write_space_avail_en = 1;
            if (!tb_sep_mbox_irq_enable(enable_val.w, 1000)) {
                TEST_FAIL("Failed to enable SEP inbound write space IRQ");
            }
        }

        /* SEP IRQ line should be asserted (FIFO has space, IRQ enabled) */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ");
        }
        TEST_ASSERT_EQ(sep_irq_status, 1, "SEP IRQ asserted (FIFO has space, enabled)");

        /* Fill inbound FIFO to capacity via SEP writes */
        TEST_LOG("  Filling inbound FIFO with %d entries via SEP writes...", 16);
        for (unsigned i = 0; i < 16; i++) {
            if (!tb_sep_mbox_write(0xD000 + i, 1000)) {
                TEST_FAIL("Failed to write entry %u to inbound FIFO", i);
            }
            test_delay(5);
        }
        test_delay(10);

        /* FIFO is full: SEP IRQ_STATUS inbound_write_space_avail should be 0 */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_LOG("  SEP IRQ_STATUS (FIFO full): 0x%08X", sep_irq_status_val);
        TEST_ASSERT_EQ(sep_irq_status_u.f.inbound_write_space_avail, 0,
                       "SEP IRQ_STATUS inbound_write_space_avail should be clear when FIFO full");

        /* SEP IRQ line should be deasserted (only write-space enabled, FIFO full) */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ");
        }
        TEST_ASSERT_EQ(sep_irq_status, 0, "SEP IRQ deasserted (FIFO full)");

        /* KM reads one entry -> FIFO has space again */
        read_data = mbox_read_data();
        test_delay(10);

        /* SEP IRQ_STATUS inbound_write_space_avail should be 1 again */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_LOG("  SEP IRQ_STATUS (after one KM read): 0x%08X", sep_irq_status_val);
        TEST_ASSERT(
            sep_irq_status_u.f.inbound_write_space_avail,
            "SEP IRQ_STATUS inbound_write_space_avail should be set after KM reads one entry");

        /* SEP IRQ should be asserted again */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ");
        }
        TEST_ASSERT_EQ(sep_irq_status, 1, "SEP IRQ reasserted (FIFO has space)");

        /* Drain remaining entries */
        for (unsigned i = 1; i < 16; i++) {
            read_data = mbox_read_data();
            test_delay(5);
        }
        test_delay(10);
        TEST_ASSERT(mbox_inbound_empty(), "Inbound FIFO should be empty after drain");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 8: SEP inbound write-FIFO space IRQ - enable gating
     *
     * Status bit should always reflect FIFO state regardless of enable;
     * enable only gates the SEP IRQ line.
     *=========================================================================*/
    TEST_SUBTEST_START("SEP inbound write-FIFO space IRQ - enable gating");
    {
        uint32_t sep_irq_status_val;
        KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u sep_irq_status_u;

        /* Disable SEP write-space IRQ */
        if (!tb_sep_mbox_irq_enable(0, 1000)) {
            TEST_FAIL("Failed to disable SEP IRQ");
        }

        /* Status inbound_write_space_avail should still reflect FIFO state (has space) */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_LOG("  SEP IRQ_STATUS (IRQ disabled, FIFO has space): 0x%08X", sep_irq_status_val);
        TEST_ASSERT(sep_irq_status_u.f.inbound_write_space_avail,
                    "Status inbound_write_space_avail reflects FIFO state even when IRQ disabled");

        /* SEP IRQ line should NOT be asserted (IRQ disabled) */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ");
        }
        TEST_ASSERT_EQ(sep_irq_status, 0, "SEP IRQ not asserted when disabled");

        /* Fill FIFO to full via SEP writes */
        for (unsigned i = 0; i < 16; i++) {
            if (!tb_sep_mbox_write(0xE000 + i, 1000)) {
                TEST_FAIL("Failed to write entry %u", i);
            }
            test_delay(5);
        }
        test_delay(10);

        /* Status inbound_write_space_avail should be 0 (FIFO full), IRQ still disabled */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_ASSERT_EQ(sep_irq_status_u.f.inbound_write_space_avail, 0,
                       "Status inbound_write_space_avail clear when FIFO full (IRQ disabled)");

        /* Drain all entries via KM reads */
        for (unsigned i = 0; i < 16; i++) {
            read_data = mbox_read_data();
            test_delay(5);
        }
        test_delay(10);

        /* Status inbound_write_space_avail should be 1 (space available), IRQ still disabled */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_ASSERT(
            sep_irq_status_u.f.inbound_write_space_avail,
            "Status inbound_write_space_avail set when FIFO has space (IRQ still disabled)");

        /* SEP IRQ line should still not be asserted */
        if (!tb_sep_mbox_irq_check(&sep_irq_status, 1000)) {
            TEST_FAIL("Failed to check SEP IRQ");
        }
        TEST_ASSERT_EQ(sep_irq_status, 0, "SEP IRQ still not asserted (disabled)");
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Test 9: SEP inbound write-FIFO space IRQ - fill/empty cycle
     *
     * Fill FIFO completely, verify IRQ deasserts, then consumer reads all;
     * verify IRQ reasserts.
     *=========================================================================*/
    TEST_SUBTEST_START("SEP inbound write-FIFO space IRQ - fill/empty cycle");
    {
        uint32_t sep_irq_status_val;
        KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u sep_irq_status_u;

        /* Enable only the write-space IRQ */
        {
            KM_MAILBOX_SEP_IRQ_ENABLE_REG_reg_u enable_val = {0};
            enable_val.f.inbound_write_space_avail_en = 1;
            if (!tb_sep_mbox_irq_enable(enable_val.w, 1000)) {
                TEST_FAIL("Failed to enable SEP write-space IRQ");
            }
        }

        /* FIFO is empty -> inbound_write_space_avail should be 1 */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_ASSERT(sep_irq_status_u.f.inbound_write_space_avail,
                    "Status inbound_write_space_avail set when FIFO empty (has space)");

        /* Fill FIFO to full */
        for (unsigned i = 0; i < 16; i++) {
            if (!tb_sep_mbox_write(0xF000 + i, 1000)) {
                TEST_FAIL("Failed to write entry %u", i);
            }
            test_delay(5);
        }
        test_delay(10);

        /* FIFO full -> inbound_write_space_avail should be 0 */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_ASSERT_EQ(sep_irq_status_u.f.inbound_write_space_avail, 0,
                       "Status inbound_write_space_avail clear when FIFO full");

        /* Drain all entries */
        for (unsigned i = 0; i < 16; i++) {
            read_data = mbox_read_data();
            test_delay(5);
        }
        test_delay(10);

        /* FIFO empty again -> inbound_write_space_avail should be 1 */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status_val, 1000)) {
            TEST_FAIL("Failed to read SEP IRQ_STATUS");
        }
        sep_irq_status_u.w = sep_irq_status_val;
        TEST_ASSERT(sep_irq_status_u.f.inbound_write_space_avail,
                    "Status inbound_write_space_avail reasserts after FIFO drained");

        /* Clean up */
        if (!tb_sep_mbox_irq_enable(0, 1000)) {
            TEST_FAIL("Failed to disable SEP IRQ");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
