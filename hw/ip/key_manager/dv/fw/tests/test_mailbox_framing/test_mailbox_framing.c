/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_framing.c
 * @brief Mailbox message framing test
 *
 * Verifies the per-word message separator bit: sender sets separator on last
 * word of a message; receiver sees INBOUND_SEPARATOR / OUTBOUND_SEPARATOR in
 * STATUS after each read. Both SEP and KM transmit two messages each.
 *
 * Tests:
 * - Part A: SEP sends two messages (msg1: 3 words, msg2: 2 words); KM reads
 *   all 5 words and checks INBOUND_SEPARATOR after each read (0,0,1, 0,1).
 * - Part B: KM sends two messages (msg1: 2 words, msg2: 2 words); SEP reads
 *   all 4 words and checks OUTBOUND_SEPARATOR after each read (0,1, 0,1).
 *
 * KM-side register constants come from key_manager_fw.h (PeakRDL-generated
 * from key_manager.rdl). SEP-side operations (tb_sep_mbox_write_separator_write,
 * tb_sep_mbox_status_read) use macros from km_mailbox_sep_regs.h.
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_framing
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "km_mailbox_sep_regs.h"

/* KM-side mailbox register access (addresses and types from key_manager_fw.h) */
#define MBOX_WRITE_DATA_REG \
    (*(volatile km_mailbox_km__write_data_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR)
#define MBOX_WRITE_SEPARATOR_REG \
    (*(volatile km_mailbox_km__write_separator_reg_t *) \
         KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR)
#define MBOX_READ_DATA_REG \
    (*(volatile km_mailbox_km__read_data_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR)
#define MBOX_STATUS_REG \
    (*(volatile km_mailbox_km__status_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR)

#define TB_TIMEOUT_CYCLES 5000

static inline uint32_t mbox_read_status(void) {
    return MBOX_STATUS_REG.w;
}

static inline uint32_t mbox_read_data(void) {
    return MBOX_READ_DATA_REG.w;
}

static inline void mbox_write_data(uint32_t data) {
    MBOX_WRITE_DATA_REG.w = data;
}

static inline int mbox_inbound_empty(void) {
    return MBOX_STATUS_REG.f.inbound_empty != 0;
}

/**
 * Wait for inbound FIFO to become non-empty (with timeout).
 */
static int mbox_wait_for_inbound_data(uint32_t timeout_cycles) {
    for (uint32_t i = 0; i < timeout_cycles; i++) {
        if (!mbox_inbound_empty()) {
            return 1;
        }
        test_delay(1);
    }
    return 0;
}

int main(void) {
    uint32_t st;
    uint32_t d;
    uint32_t sep_status;
    /* Expected INBOUND_SEPARATOR after each of 5 KM reads: 0,0,1, 0,1 */
    static const int expected_inbound_sep[] = {0, 0, 1, 0, 1};
    /* Expected OUTBOUND_SEPARATOR after each of 4 SEP reads: 0,1, 0,1 */
    static const int expected_outbound_sep[] = {0, 1, 0, 1};

    TEST_INIT();

    /*=========================================================================
     * Part A: SEP sends two messages; KM reads all words and checks
     *         INBOUND_SEPARATOR after each read.
     *         Msg1: 0x11111111, 0x22222222, 0x33333333 (sep on last)
     *         Msg2: 0x44444444, 0x55555555 (sep on last)
     *=========================================================================*/
    TEST_SUBTEST_START("SEP→KM: two messages (3+2 words), KM checks INBOUND_SEPARATOR");
    {
        /* SEP message 1: 3 words, separator on last */
        if (!tb_sep_mbox_write(0x11111111u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write msg1 word1 failed");
        }
        if (!tb_sep_mbox_write(0x22222222u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write msg1 word2 failed");
        }
        if (!tb_sep_mbox_write_separator_write(1, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write_separator_write (set separator msg1) failed");
        }
        if (!tb_sep_mbox_write(0x33333333u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write msg1 word3 failed");
        }

        /* SEP message 2: 2 words, separator on last */
        if (!tb_sep_mbox_write(0x44444444u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write msg2 word1 failed");
        }
        if (!tb_sep_mbox_write_separator_write(1, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write_separator_write (set separator msg2) failed");
        }
        if (!tb_sep_mbox_write(0x55555555u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write msg2 word2 failed");
        }

        if (!mbox_wait_for_inbound_data(TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("Timeout waiting for inbound data");
        }

        {
            static const uint32_t expected[] = {0x11111111u, 0x22222222u, 0x33333333u, 0x44444444u,
                                                0x55555555u};
            for (int i = 0; i < 5; i++) {
                d = mbox_read_data();
                st = mbox_read_status();
                {
                    km_mailbox_km__status_reg_t st_u = {.w = st};
                    TEST_ASSERT(d == expected[i], "KM read word %d value", i + 1);
                    TEST_ASSERT((st_u.f.inbound_separator != 0) == (expected_inbound_sep[i] != 0),
                                "INBOUND_SEPARATOR after KM read %d (expect %d)", i + 1,
                                expected_inbound_sep[i]);
                }
            }
        }
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Part B: KM sends two messages; SEP reads all words and checks
     *         OUTBOUND_SEPARATOR after each read.
     *         Msg1: 0xAAAA5555, 0x5555AAAA (sep on last)
     *         Msg2: 0xDEADBEEF, 0xBEEFDEAD (sep on last)
     *=========================================================================*/
    TEST_SUBTEST_START("KM→SEP: two messages (2+2 words), SEP checks OUTBOUND_SEPARATOR");
    {
        /* KM message 1: 2 words, separator on last */
        mbox_write_data(0xAAAA5555u);
        test_delay(2);
        MBOX_WRITE_SEPARATOR_REG.w = 1;
        mbox_write_data(0x5555AAAAu);
        test_delay(2);

        /* KM message 2: 2 words, separator on last (separator bit cleared by hw on push) */
        mbox_write_data(0xDEADBEEFu);
        test_delay(2);
        MBOX_WRITE_SEPARATOR_REG.w = 1;
        mbox_write_data(0xBEEFDEADu);
        test_delay(2);

        {
            static const uint32_t expected[] = {0xAAAA5555u, 0x5555AAAAu, 0xDEADBEEFu, 0xBEEFDEADu};
            for (int i = 0; i < 4; i++) {
                if (!tb_sep_mbox_read(&d, TB_TIMEOUT_CYCLES)) {
                    TEST_FAIL("tb_sep_mbox_read word %d failed", i + 1);
                }
                if (!tb_sep_mbox_status_read(&sep_status, TB_TIMEOUT_CYCLES)) {
                    TEST_FAIL("tb_sep_mbox_status_read after word %d failed", i + 1);
                }
                {
                    KM_MAILBOX_SEP_STATUS_REG_reg_u sep_status_u = {.w = sep_status};
                    TEST_ASSERT(d == expected[i], "SEP read word %d value", i + 1);
                    TEST_ASSERT((sep_status_u.f.outbound_separator != 0) ==
                                    (expected_outbound_sep[i] != 0),
                                "OUTBOUND_SEPARATOR after SEP read %d (expect %d)", i + 1,
                                expected_outbound_sep[i]);
                }
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
