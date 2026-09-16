/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_mailbox_flush_overlap.c
 * @brief KM READ_DATA AR overlapped with SEP CTRL.FLUSH
 *
 * Fills the inbound FIFO, then asks the testbench to write SEP CTRL.FLUSH and
 * issue a KM READ_DATA AR on the one-cycle flush-active window. The AR must
 * complete with an R beat; hanging until reset is a failure.
 *
 * Run with:
 *   make run_fw FW_TEST=test_mailbox_flush_overlap
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define MBOX_STATUS_REG \
    (*(volatile km_mailbox_km__status_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR)

#define TB_TIMEOUT_CYCLES 5000

int main(void) {
    TEST_INIT();

    TEST_SUBTEST_START("KM READ_DATA AR completes when SEP flush races the pop");
    {
        if (!tb_sep_mbox_write(0xA5A5A5A5u, TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("tb_sep_mbox_write inbound word failed");
        }
        if (MBOX_STATUS_REG.f.inbound_empty != 0) {
            TEST_FAIL("Inbound FIFO should be non-empty before overlap");
        }
        if (!tb_km_mbox_read_during_sep_flush(TB_TIMEOUT_CYCLES)) {
            TEST_FAIL("READ_DATA AR that races SEP flush did not complete");
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
