/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_counters.c
 * @brief DRBG Sampler COUNT_GOOD/COUNT_BAD saturation and clear test
 *
 * Verifies (1) COUNT_GOOD saturates at 0xFFFF (no overflow), (2) COUNT_BAD
 * saturates at 0xFF (no overflow), and (3) writing any value other than 0
 * to the COUNT_GOOD or COUNT_BAD field of the STATUS register clears that
 * counter to 0.
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_counters
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DRBG Sampler registers */
#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)
#define DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)

#define COUNT_GOOD_MAX 0xFFFFu
#define COUNT_BAD_MAX 0xFFu

/*
 * COUNT_GOOD full saturation: 65536 successful reads to reach 0xFFFF, then one
 * more read to verify no overflow. (Test may take several minutes in simulation.)
 */
#define READS_FOR_GOOD_SATURATION (COUNT_GOOD_MAX + 1u) /* 65536 reads to saturate */

/* Number of timeouts to saturate COUNT_BAD (8-bit); each read blocks ~TIMEOUT cycles */
#define TIMEOUTS_FOR_BAD_SATURATION (COUNT_BAD_MAX + 1u)
#define DRBG_TIMEOUT_CYCLES 5u

/* Loop: read DATA, check STATUS.timeout_err; repeat until set or limit (see test_drbg_timeout.c) */
#define DATA_READ_UNTIL_TIMEOUT_MAX 20u

/**
 * Read DATA repeatedly and check STATUS.timeout_err each time. After stop, TB
 * may complete one beat so the first read can succeed; a later read will time out.
 * Returns 1 if timeout_err was set, 0 if loop limit reached without timeout.
 */
static int data_read_until_timeout_err(void) {
    for (uint32_t i = 0; i < DATA_READ_UNTIL_TIMEOUT_MAX; i++) {
        (void)DRBG_DATA_REG.f.data;
        if (DRBG_STATUS_REG.f.timeout_err != 0u) {
            return 1;
        }
    }
    return 0;
}

/**
 * Clear STATUS.timeout_err (W1C). Use before triggering a fresh timeout.
 */
static void clear_drbg_timeout_status(void) {
    km_drbg_sampler__status_reg_t w1c = {0};
    w1c.f.timeout_err = 1;
    DRBG_STATUS_REG.w = w1c.w;
}

/**
 * Clear COUNT_GOOD by writing non-zero to the COUNT_GOOD field [31:16] of STATUS.
 * Other bits (e.g. W1C) can be 0 to avoid side effects.
 */
static void clear_count_good(void) {
    km_drbg_sampler__status_reg_t w = {0};
    w.f.count_good = 1u; /* Any non-zero clears COUNT_GOOD to 0 */
    DRBG_STATUS_REG.w = w.w;
}

/**
 * Clear COUNT_BAD by writing non-zero to the COUNT_BAD field [15:8] of STATUS.
 */
static void clear_count_bad(void) {
    km_drbg_sampler__status_reg_t w = {0};
    w.f.count_bad = 1u; /* Any non-zero clears COUNT_BAD to 0 */
    DRBG_STATUS_REG.w = w.w;
}

/**
 * Clear both counters (write non-zero to both fields).
 */
static void clear_both_counters(void) {
    km_drbg_sampler__status_reg_t w = {0};
    w.f.count_good = 1u;
    w.f.count_bad = 1u;
    DRBG_STATUS_REG.w = w.w;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(5000000)) {
        TEST_FAIL("tb_set_timeout failed");
    }
    if (!tb_drbg_set_seed(1, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /* CFG: prefetch off, timeout for later COUNT_BAD test */
    DRBG_CFG_REG.w = 0;
    DRBG_CFG_REG.f.timeout = (uint16_t)DRBG_TIMEOUT_CYCLES;

    /*--------------------------------------------------------------------------
     * COUNT_GOOD saturation: do 65536 successful reads, then one more.
     * COUNT_GOOD must saturate at 0xFFFF and not overflow.
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("COUNT_GOOD saturation");
    clear_both_counters();
    if (DRBG_STATUS_REG.f.count_good != 0u || DRBG_STATUS_REG.f.count_bad != 0u) {
        TEST_FAIL("Counters not zero after clear");
    }

    for (uint32_t i = 0; i < READS_FOR_GOOD_SATURATION; i++) {
        (void)DRBG_DATA_REG.f.data;
    }
    if (DRBG_STATUS_REG.f.count_good != COUNT_GOOD_MAX) {
        TEST_FAIL("COUNT_GOOD not saturated at 0xFFFF after %u reads (got %u)",
                  (unsigned)READS_FOR_GOOD_SATURATION, (unsigned)DRBG_STATUS_REG.f.count_good);
    }
    /* One more read: must still be 0xFFFF (no overflow) */
    (void)DRBG_DATA_REG.f.data;
    if (DRBG_STATUS_REG.f.count_good != COUNT_GOOD_MAX) {
        TEST_FAIL("COUNT_GOOD overflowed (expected 0xFFFF, got %u)",
                  (unsigned)DRBG_STATUS_REG.f.count_good);
    }
    TEST_LOG("  COUNT_GOOD saturated at 0xFFFF, no overflow");
    TEST_SUBTEST_PASS();

    /*--------------------------------------------------------------------------
     * COUNT_BAD saturation: stop DRBG, then 256 timeouts; one more timeout.
     * COUNT_BAD must saturate at 0xFF and not overflow.
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("COUNT_BAD saturation");
    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed");
    }
    clear_count_good();
    clear_count_bad();

    for (uint32_t i = 0; i < TIMEOUTS_FOR_BAD_SATURATION; i++) {
        (void)DRBG_DATA_REG.f.data;
    }
    if (DRBG_STATUS_REG.f.count_bad != COUNT_BAD_MAX) {
        TEST_FAIL("COUNT_BAD not saturated at 0xFF after %u timeouts (got %u)",
                  (unsigned)TIMEOUTS_FOR_BAD_SATURATION, (unsigned)DRBG_STATUS_REG.f.count_bad);
    }
    /* One more timeout: COUNT_BAD must stay 0xFF */
    (void)DRBG_DATA_REG.f.data;
    while (DRBG_STATUS_REG.f.timeout_err == 0u) {
        test_delay(1);
    }
    if (DRBG_STATUS_REG.f.count_bad != COUNT_BAD_MAX) {
        TEST_FAIL("COUNT_BAD overflowed (expected 0xFF, got %u)",
                  (unsigned)DRBG_STATUS_REG.f.count_bad);
    }
    TEST_LOG("  COUNT_BAD saturated at 0xFF, no overflow");
    TEST_SUBTEST_PASS();

    if (!tb_drbg_start(1000)) {
        TEST_FAIL("tb_drbg_start failed");
    }

    /*--------------------------------------------------------------------------
     * Clear counters: write non-zero to COUNT_GOOD and COUNT_BAD, verify both 0.
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("Clear COUNT_GOOD and COUNT_BAD");
    clear_both_counters();
    if (DRBG_STATUS_REG.f.count_good != 0u) {
        TEST_FAIL("COUNT_GOOD not zero after clear (got %u)",
                  (unsigned)DRBG_STATUS_REG.f.count_good);
    }
    if (DRBG_STATUS_REG.f.count_bad != 0u) {
        TEST_FAIL("COUNT_BAD not zero after clear (got %u)", (unsigned)DRBG_STATUS_REG.f.count_bad);
    }
    TEST_LOG("  Both counters reset to 0");
    TEST_SUBTEST_PASS();

    /*--------------------------------------------------------------------------
     * Clear independently: raise COUNT_GOOD, clear only COUNT_GOOD; same for COUNT_BAD.
     *--------------------------------------------------------------------------*/
    TEST_SUBTEST_START("Clear COUNT_GOOD only");
    (void)DRBG_DATA_REG.f.data;
    (void)DRBG_DATA_REG.f.data;
    if (DRBG_STATUS_REG.f.count_good < 2u) {
        TEST_FAIL("COUNT_GOOD did not increment");
    }
    clear_count_good();
    if (DRBG_STATUS_REG.f.count_good != 0u) {
        TEST_FAIL("COUNT_GOOD not zero after clear (got %u)",
                  (unsigned)DRBG_STATUS_REG.f.count_good);
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Clear COUNT_BAD only");
    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed");
    }
    clear_drbg_timeout_status();
    if (DRBG_STATUS_REG.f.timeout_err != 0u) {
        TEST_FAIL("STATUS.TIMEOUT_ERR not clear before triggering timeout");
    }
    /* DATA must be read in a loop until timeout occurs (see test_drbg_timeout.c) */
    if (!data_read_until_timeout_err()) {
        TEST_FAIL("STATUS.TIMEOUT_ERR not set after %u DATA reads (limit reached)",
                  (unsigned)DATA_READ_UNTIL_TIMEOUT_MAX);
    }
    if (DRBG_STATUS_REG.f.count_bad == 0u) {
        TEST_FAIL("COUNT_BAD did not increment");
    }
    clear_count_bad();
    if (DRBG_STATUS_REG.f.count_bad != 0u) {
        TEST_FAIL("COUNT_BAD not zero after clear (got %u)", (unsigned)DRBG_STATUS_REG.f.count_bad);
    }
    TEST_SUBTEST_PASS();

    if (!tb_drbg_start(1000)) {
        TEST_FAIL("tb_drbg_start failed");
    }

    TEST_PASS();
    return 0;
}
