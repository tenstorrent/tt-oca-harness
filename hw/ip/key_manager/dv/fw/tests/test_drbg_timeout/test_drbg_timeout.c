/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_timeout.c
 * @brief DRBG Sampler timeout and KMCSR IRQ test
 *
 * Pulls a couple beats of data from the DRBG, sends stop command (TB stops
 * after current beat per AXI-Stream rule). TB may still complete one beat;
 * we loop: read DATA, then check STATUS.timeout_err, until timeout occurs.
 * Then verify KMCSR IRQ_STATUS.DRBG_ERR. Runs with prefetch disabled and enabled.
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_timeout
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DRBG Sampler registers (struct-based access from km_drbg_sampler.h) */
#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)
#define DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)
/* KMCSR IRQ regs: use KMCSR_IRQ_STATUS_REG / KMCSR_IRQ_ENABLE_REG from irq_common.h */

#define DRBG_TIMEOUT_CYCLES \
    256u /* CFG.TIMEOUT value for test (RTL waits this long then sets TIMEOUT_ERR) */
#define DATA_READ_UNTIL_TIMEOUT_MAX \
    20u /* Loop: read DATA, check STATUS.timeout_err; repeat until set or limit */

static void clear_drbg_timeout_status(void) {
    km_drbg_sampler__status_reg_t w1c = {0};
    w1c.f.timeout_err = 1;
    DRBG_STATUS_REG.w = w1c.w;
}

static void clear_kmcsr_drbg_err(void) {
    km_csr__irq_status_reg_t w1c = {0};
    w1c.f.drbg_err = 1;
    rom_kmcsr_irq_status_clear(w1c.w);
}

static void enable_drbg_irq(void) {
    km_csr__irq_enable_reg_t en = {.w = rom_kmcsr_irq_enable_read()};
    en.f.drbg_err_en = 1;
    rom_kmcsr_irq_enable_write(en.w);
}

/**
 * Read DATA repeatedly and check STATUS.timeout_err each time. After stop, TB
 * may complete one beat so the first read can succeed; a later read will time out.
 * Returns 1 if timeout_err was set, 0 if loop limit reached without timeout.
 */
static int data_read_until_timeout_err(void) {
    for (uint32_t i = 0; i < DATA_READ_UNTIL_TIMEOUT_MAX; i++) {
        (void)DRBG_DATA_REG.f.data;
        if (DRBG_STATUS_REG.f.timeout_err != 0) {
            return 1;
        }
    }
    return 0;
}

int main(void) {
    TEST_INIT();

    /* Test timeout: two subtests; each can do up to 20 DATA reads × 256-cycle RTL timeout + TB cmd
     * ack */
    if (!tb_set_timeout(30000)) {
        TEST_FAIL("tb_set_timeout failed");
    }

    if (!tb_drbg_set_seed(1, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /* DRBG CFG: timeout for active read; prefetch set per subtest */
    DRBG_CFG_REG.w = 0;
    DRBG_CFG_REG.f.timeout = (uint16_t)DRBG_TIMEOUT_CYCLES;
    enable_drbg_irq();

    /*--------------------------------------------------------------------------
     * Prefetch disabled: 2 beats, stop, next read times out → TIMEOUT_ERR + DRBG_ERR
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("DRBG timeout without prefetch");
    DRBG_CFG_REG.f.prefetch = 0;
    clear_drbg_timeout_status();
    clear_kmcsr_drbg_err();
    if (DRBG_STATUS_REG.f.timeout_err != 0) {
        TEST_FAIL("STATUS.TIMEOUT_ERR not clear at start");
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err != 0) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not clear at start");
    }

    (void)DRBG_DATA_REG.f.data; /* beat 1 */
    (void)DRBG_DATA_REG.f.data; /* beat 2 */

    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed");
    }

    /* Loop: read DATA, check STATUS.timeout_err (first read may consume TB's last beat) */
    if (!data_read_until_timeout_err()) {
        TEST_FAIL("STATUS.TIMEOUT_ERR not set after %u DATA reads (limit reached)",
                  (unsigned)DATA_READ_UNTIL_TIMEOUT_MAX);
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err == 0) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not set");
    }
    if (DRBG_STATUS_REG.f.drbg_ready != 0) {
        TEST_FAIL("STATUS.DRBG_READY set after timeout (TB stopped, TVALID=0)");
    }
    if (DRBG_STATUS_REG.f.count_bad == 0) {
        TEST_FAIL("STATUS.COUNT_BAD not incremented after timeout");
    }
    TEST_LOG(
        "  TIMEOUT_ERR and DRBG_ERR set, DRBG_READY clear, COUNT_BAD incremented (prefetch off)");
    TEST_SUBTEST_PASS();

    clear_drbg_timeout_status();
    clear_kmcsr_drbg_err();
    if (!tb_drbg_start(1000)) {
        TEST_FAIL("tb_drbg_start failed");
    }

    /*--------------------------------------------------------------------------
     * Prefetch enabled: 2 beats, stop, next read times out → TIMEOUT_ERR + DRBG_ERR
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("DRBG timeout with prefetch");
    DRBG_CFG_REG.f.prefetch = 1;
    clear_drbg_timeout_status();
    clear_kmcsr_drbg_err();
    if (DRBG_STATUS_REG.f.timeout_err != 0) {
        TEST_FAIL("STATUS.TIMEOUT_ERR not clear at start");
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err != 0) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not clear at start");
    }

    (void)DRBG_DATA_REG.f.data; /* beat 1 */
    (void)DRBG_DATA_REG.f.data; /* beat 2 */

    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed");
    }

    /* Loop: read DATA, check STATUS.timeout_err (first read may consume TB's last beat) */
    if (!data_read_until_timeout_err()) {
        TEST_FAIL("STATUS.TIMEOUT_ERR not set after %u DATA reads (limit reached)",
                  (unsigned)DATA_READ_UNTIL_TIMEOUT_MAX);
    }
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err == 0) {
        TEST_FAIL("IRQ_STATUS.DRBG_ERR not set");
    }
    if (DRBG_STATUS_REG.f.drbg_ready != 0) {
        TEST_FAIL("STATUS.DRBG_READY set after timeout (TB stopped, TVALID=0)");
    }
    if (DRBG_STATUS_REG.f.count_bad == 0) {
        TEST_FAIL("STATUS.COUNT_BAD not incremented after timeout");
    }
    TEST_LOG(
        "  TIMEOUT_ERR and DRBG_ERR set, DRBG_READY clear, COUNT_BAD incremented (prefetch on)");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
