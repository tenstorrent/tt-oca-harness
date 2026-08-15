/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_flush.c
 * @brief Mailbox flush test
 *
 * Verifies (1a) SEP flush clears both FIFOs; (1b) KM flush clears both FIFOs;
 * (2) SEP flush -> KM interrupt (FLUSHED_BY_SEP); (3) KM flush -> SEP
 * interrupt (FLUSHED_BY_KM).
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_flush
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "km_mailbox_sep_regs.h"

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

#define TB_TIMEOUT_CYCLES 5000

static inline uint32_t mbox_read_status(void) {
    return MBOX_STATUS_REG.w;
}

static inline void mbox_write_data(uint32_t data) {
    MBOX_WRITE_DATA_REG.w = data;
}

static inline int mbox_inbound_empty(void) {
    return MBOX_STATUS_REG.f.inbound_empty != 0;
}

static inline int mbox_outbound_empty(void) {
    return MBOX_STATUS_REG.f.outbound_empty != 0;
}

static int poll_km_irq_flushed_by_sep(uint32_t timeout_cycles) {
    for (uint32_t i = 0; i < timeout_cycles; i++) {
        if (MBOX_IRQ_STATUS_REG.f.flushed_by_sep != 0) {
            return 1;
        }
    }
    return 0;
}

int main(void) {
    uint32_t st;
    uint32_t sep_irq_status;

    TEST_INIT();

    /*=========================================================================
     * Part 1a: SEP flush clears both FIFOs
     *=========================================================================*/
    TEST_SUBTEST_START("Data flush: SEP flush clears both FIFOs");
    {
        /* TB writes to inbound FIFO */
        if (!tb_sep_mbox_write(0xAAAAAAAAu, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write inbound word failed");
        }
        if (!tb_sep_mbox_write(0xBBBBBBBBu, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write inbound word 2 failed");
        }
        /* KM writes to outbound FIFO */
        mbox_write_data(0xCCCCCCCCu);
        mbox_write_data(0xDDDDDDDDu);

        /* Verify both FIFOs non-empty before flush */
        st = mbox_read_status();
        if (mbox_inbound_empty()) {
            TEST_FAIL("Inbound FIFO should be non-empty before SEP flush (st=0x%08X)",
                      (unsigned)st);
        }
        if (mbox_outbound_empty()) {
            TEST_FAIL("Outbound FIFO should be non-empty before SEP flush (st=0x%08X)",
                      (unsigned)st);
        }

        /* SEP performs flush */
        {
            KM_MAILBOX_SEP_CTRL_REG_reg_u ctrl_val = {0};
            ctrl_val.f.flush = 1;
            if (!tb_sep_mbox_ctrl_write(ctrl_val.w, TB_TIMEOUT_CYCLES)) {
                TEST_FAIL("tb_sep_mbox_ctrl_write FLUSH failed");
            }
        }

        /* Verify both FIFOs empty after SEP flush */
        st = mbox_read_status();
        if (!mbox_inbound_empty()) {
            TEST_FAIL("Inbound FIFO should be empty after SEP flush (st=0x%08X)", (unsigned)st);
        }
        if (!mbox_outbound_empty()) {
            TEST_FAIL("Outbound FIFO should be empty after SEP flush (st=0x%08X)", (unsigned)st);
        }

        /* Clear IRQ: KM saw FLUSHED_BY_SEP (SEP initiated flush) */
        {
            km_mailbox_km__irq_status_reg_t w1c = {0};
            w1c.f.flushed_by_sep = 1;
            MBOX_IRQ_STATUS_REG.w = w1c.w;
        }
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Part 1b: KM flush clears both FIFOs
     *=========================================================================*/
    TEST_SUBTEST_START("Data flush: KM flush clears both FIFOs");
    {
        /* Fill both FIFOs */
        if (!tb_sep_mbox_write(0x11111111u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write inbound word failed");
        }
        mbox_write_data(0x22222222u);

        st = mbox_read_status();
        if (mbox_inbound_empty()) {
            TEST_FAIL("Inbound FIFO should be non-empty before KM flush (st=0x%08X)", (unsigned)st);
        }
        if (mbox_outbound_empty()) {
            TEST_FAIL("Outbound FIFO should be non-empty before KM flush (st=0x%08X)",
                      (unsigned)st);
        }

        /* KM performs flush */
        {
            km_mailbox_km__ctrl_reg_t ctrl_val = {0};
            ctrl_val.f.flush = 1;
            MBOX_CTRL_REG.w = ctrl_val.w;
        }
        test_delay(2); /* Allow FIFO clear to take effect */

        /* Verify both FIFOs empty after KM flush */
        st = mbox_read_status();
        if (!mbox_inbound_empty()) {
            TEST_FAIL("Inbound FIFO should be empty after KM flush (st=0x%08X)", (unsigned)st);
        }
        if (!mbox_outbound_empty()) {
            TEST_FAIL("Outbound FIFO should be empty after KM flush (st=0x%08X)", (unsigned)st);
        }

        /* Clear IRQ: SEP saw FLUSHED_BY_KM (KM initiated flush) */
        {
            KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u w1c = {0};
            w1c.f.flushed_by_km = 1;
            if (!tb_sep_mbox_irq_status_write(w1c.w, TB_TIMEOUT_CYCLES)) {
                TEST_FAIL("tb_sep_mbox_irq_status_write (clear FLUSHED_BY_KM) failed");
            }
        }
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Part 2: SEP flush -> KM interrupt (FLUSHED_BY_SEP)
     * KM enables FLUSHED_BY_SEP IRQ; TB does SEP CTRL.FLUSH; KM polls until
     * IRQ_STATUS.FLUSHED_BY_SEP; verify initiator (SEP) does not have its
     * flush bit (FLUSHED_BY_KM) set; then clear FLUSHED_BY_SEP.
     *=========================================================================*/
    TEST_SUBTEST_START("SEP flush -> KM sees FLUSHED_BY_SEP");
    {
        /* Enable FLUSHED_BY_SEP interrupt on KM side */
        {
            km_mailbox_km__irq_enable_reg_t enable_val = {0};
            enable_val.f.flushed_by_sep_en = 1;
            MBOX_IRQ_ENABLE_REG.w = enable_val.w;
        }

        /* TB performs SEP flush */
        {
            KM_MAILBOX_SEP_CTRL_REG_reg_u ctrl_val = {0};
            ctrl_val.f.flush = 1;
            if (!tb_sep_mbox_ctrl_write(ctrl_val.w, TB_TIMEOUT_CYCLES)) {
                TEST_FAIL("tb_sep_mbox_ctrl_write FLUSH failed");
            }
        }

        /* KM polls until FLUSHED_BY_SEP set */
        if (!poll_km_irq_flushed_by_sep(TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("FLUSHED_BY_SEP not set after SEP flush (IRQ_STATUS=0x%08X)",
                      (unsigned)MBOX_IRQ_STATUS_REG.w);
        }

        /* Initiator was SEP: SEP must not have FLUSHED_BY_KM set */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_irq_status_read failed");
        }
        {
            KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u sep_irq_u = {.w = sep_irq_status};
            if (sep_irq_u.f.flushed_by_km != 0) {
                TEST_FAIL("SEP (initiator) should not have FLUSHED_BY_KM set (IRQ_STATUS=0x%08X)",
                          (unsigned)sep_irq_status);
            }
        }

        /* Clear FLUSHED_BY_SEP (W1C) */
        {
            km_mailbox_km__irq_status_reg_t w1c = {0};
            w1c.f.flushed_by_sep = 1;
            MBOX_IRQ_STATUS_REG.w = w1c.w;
        }
        if (MBOX_IRQ_STATUS_REG.f.flushed_by_sep != 0) {
            TEST_FAIL("FLUSHED_BY_SEP not cleared after W1C");
        }
    }
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Part 3: KM flush -> SEP interrupt (FLUSHED_BY_KM)
     * KM writes CTRL.FLUSH; TB reads SEP mailbox IRQ_STATUS and verifies
     * FLUSHED_BY_KM; verify initiator (KM) does not have its flush bit
     * (FLUSHED_BY_SEP) set.
     *=========================================================================*/
    TEST_SUBTEST_START("KM flush -> SEP sees FLUSHED_BY_KM");
    {
        /* KM performs flush */
        {
            km_mailbox_km__ctrl_reg_t ctrl_val = {0};
            ctrl_val.f.flush = 1;
            MBOX_CTRL_REG.w = ctrl_val.w;
        }

        /* Initiator was KM: KM must not have FLUSHED_BY_SEP set */
        if (MBOX_IRQ_STATUS_REG.f.flushed_by_sep != 0) {
            TEST_FAIL("KM (initiator) should not have FLUSHED_BY_SEP set (IRQ_STATUS=0x%08X)",
                      (unsigned)MBOX_IRQ_STATUS_REG.w);
        }

        /* TB reads SEP mailbox IRQ_STATUS and verifies FLUSHED_BY_KM */
        if (!tb_sep_mbox_irq_status_read(&sep_irq_status, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_irq_status_read failed");
        }
        {
            KM_MAILBOX_SEP_IRQ_STATUS_REG_reg_u sep_irq_u = {.w = sep_irq_status};
            if (sep_irq_u.f.flushed_by_km == 0) {
                TEST_FAIL("SEP IRQ_STATUS should show FLUSHED_BY_KM (read 0x%08X)",
                          (unsigned)sep_irq_status);
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
