/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_prefetch.c
 * @brief DRBG Sampler prefetch test
 *
 * Flow:
 * 1. Set deterministic seed; get from TB the value that will be prefetched when we enable
 *    prefetch (expected).
 * 2. Enable prefetch (HW performs first handshake; prefetch holds expected).
 * 3. Loop:
 *    a. Get from TB the value it will send on the next handshake (next_expected); that value
 *       will be loaded into prefetch when we read DATA in this iteration.
 *    b. Wait for PREFETCHED; verify PREFETCH_DATA and DATA equal expected.
 *    c. Read DATA (consumes prefetch and triggers handshake; prefetch is filled with
 * next_expected). d. Set expected = next_expected; repeat.
 * 4. Disable prefetch; verify PREFETCH_DATA is zero.
 * 5. Get next pending value from TB; read DATA and verify it matches (no-prefetch path).
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_prefetch
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DRBG Sampler registers (generated struct types from km_drbg_sampler.h) */
#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)
#define DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)
#define DRBG_PREFETCH_DATA_REG \
    (*(volatile km_drbg_sampler__prefetch_data_reg_t *) \
         KEY_MANAGER_DRBG_SAMPLER_PREFETCH_DATA_BASE_ADDR)

#define PREFETCH_LOOP_ITERATIONS 5
#define PREFETCH_WAIT_MAX_CYCLES 2000

static int wait_for_prefetched(void) {
    for (uint32_t i = 0; i < PREFETCH_WAIT_MAX_CYCLES; i++) {
        if (DRBG_STATUS_REG.f.prefetched != 0) {
            return 1;
        }
    }
    return 0;
}

int main(void) {
    uint32_t expected;
    uint32_t prefetch_val;
    uint32_t data_val;

    TEST_INIT();

    /* Deterministic seed for reproducible sequence */
    if (!tb_drbg_set_seed(1, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /* Start with prefetch disabled */
    DRBG_CFG_REG.w = 0;

    /* Step 1: Get the next pending value from the TB (this is what HW will prefetch) */
    if (!tb_drbg_get_next_value(&expected, 1000)) {
        TEST_FAIL("tb_drbg_get_next_value (initial) failed");
    }

    /* Step 2: Enable prefetch */
    TEST_SUBTEST_START("DRBG prefetch enable");
    DRBG_CFG_REG.f.prefetch = 1;
    TEST_ASSERT_EQ(DRBG_CFG_REG.f.prefetch, 1u, "CFG.PREFETCH");
    TEST_SUBTEST_PASS();

    /* Steps 3–6: Loop – get next expected at start (value TB will send when we read DATA); compare
     * and read; then expected for next iter is that value */
    for (int i = 0; i < PREFETCH_LOOP_ITERATIONS; i++) {
        uint32_t next_expected;
        const char *subtest_name = (i == 0)   ? "DRBG prefetch iter 1"
                                   : (i == 1) ? "DRBG prefetch iter 2"
                                   : (i == 2) ? "DRBG prefetch iter 3"
                                   : (i == 3) ? "DRBG prefetch iter 4"
                                              : "DRBG prefetch iter 5";
        TEST_SUBTEST_START(subtest_name);

        /* Get value TB will send on next handshake (loaded into prefetch when we read DATA); use as
         * expected for next iteration */
        if (!tb_drbg_get_next_value(&next_expected, 1000)) {
            TEST_FAIL("tb_drbg_get_next_value failed");
        }

        /* Use expected from previous iteration (or initial GET for i==0) for this iteration's
         * comparisons */
        if (!wait_for_prefetched()) {
            TEST_FAIL("PREFETCHED not set within timeout");
        }

        /* Step 3: PREFETCH_DATA should match value we got from TB (expected for this iteration) */
        prefetch_val = DRBG_PREFETCH_DATA_REG.f.data;
        TEST_ASSERT_EQ(prefetch_val, expected, "PREFETCH_DATA");

        /* Step 4: DATA read returns same value (consumes prefetch; RTL handshakes and prefetch gets
         * next_expected) */
        data_val = DRBG_DATA_REG.f.data;
        TEST_ASSERT_EQ(data_val, expected, "DATA");

        TEST_LOG("  PREFETCH_DATA=0x%08X DATA=0x%08X expected=0x%08X", prefetch_val, data_val,
                 expected);

        expected = next_expected;
        TEST_SUBTEST_PASS();
    }

    /* Disable prefetch; verify prefetch register is zero */
    TEST_SUBTEST_START("DRBG prefetch disable");
    DRBG_CFG_REG.f.prefetch = 0;
    TEST_ASSERT_EQ(DRBG_CFG_REG.f.prefetch, 0u, "CFG.PREFETCH");
    prefetch_val = DRBG_PREFETCH_DATA_REG.f.data;
    TEST_ASSERT_EQ(prefetch_val, 0u, "PREFETCH_DATA after disable");
    TEST_SUBTEST_PASS();

    /* No-prefetch path: get expected from TB, read DATA, verify match */
    TEST_SUBTEST_START("DRBG DATA without prefetch");
    if (!tb_drbg_get_next_value(&expected, 1000)) {
        TEST_FAIL("tb_drbg_get_next_value (no-prefetch) failed");
    }
    data_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(data_val, expected, "DATA");
    TEST_LOG("  DATA=0x%08X expected=0x%08X", data_val, expected);
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
