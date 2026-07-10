/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_recoverable_err_signal.c
 * @brief Recoverable error output signal test
 *
 * Verifies that firmware control of KMCSR RECOVERABLE_ERR is reflected on the
 * top-level recoverable_err output as sampled by the testbench command path.
 *
 * Run with:
 *   make run_fw FW_TEST=test_recoverable_err_signal
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* KMCSR RECOVERABLE_ERR register */
#define KMCSR_RECOVERABLE_ERR_REG \
    (*(volatile km_csr__recoverable_err_reg_t *)KEY_MANAGER_KMCSR_RECOVERABLE_ERR_BASE_ADDR)

int main(void) {
    TEST_INIT();

    /* Subtest 1: Set recoverable_err, ask testbench to check, expect 1 */
    TEST_SUBTEST_START("Recoverable err set");
    {
        KMCSR_RECOVERABLE_ERR_REG.f.recoverable_err = 1; /* Set recoverable status */
        test_delay(5);

        if (!tb_check_recoverable_err(1000)) {
            TEST_FAIL("Testbench did not see recoverable_err high");
        }
        if (TB_CMD_RESULT != 1) {
            TEST_FAIL("Expected TB_CMD_RESULT=1 (recoverable_err set), got 0x%08X",
                      (unsigned)TB_CMD_RESULT);
        }
    }
    TEST_SUBTEST_PASS();

    /* Subtest 2: Clear recoverable_err, ask testbench to check, expect 0 */
    TEST_SUBTEST_START("Recoverable err clear");
    {
        KMCSR_RECOVERABLE_ERR_REG.f.recoverable_err = 0; /* Clear recoverable status */
        test_delay(5);

        if (tb_check_recoverable_err(1000)) {
            TEST_FAIL("Testbench still saw recoverable_err high after clear");
        }
        if (TB_CMD_RESULT != 0) {
            TEST_FAIL("Expected TB_CMD_RESULT=0 (recoverable_err clear), got 0x%08X",
                      (unsigned)TB_CMD_RESULT);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
