/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_sanity.c
 * @brief DRBG Sampler sanity test (no prefetch)
 *
 * Verifies (1) reading random data from the DRBG (TB provides random by default),
 * and (2) override path: SET next value, then read DATA and verify it matches
 * (using TB_CMD_DRBG_GET_NEXT_VALUE to get expected).
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_sanity
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

int main(void) {
    uint32_t expected;
    uint32_t read_val;

    TEST_INIT();

    /* Set deterministic seed so "random" data is reproducible */
    if (!tb_drbg_set_seed(1, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    /* Ensure prefetch is disabled (default); CFG.PREFETCH = 0 */
    TEST_SUBTEST_START("DRBG CFG prefetch disabled");
    DRBG_CFG_REG.w = 0; /* PREFETCH=0, TIMEOUT default or 0 */
    test_delay(10);
    TEST_ASSERT_EQ(DRBG_CFG_REG.f.prefetch, 0u, "CFG.PREFETCH");
    TEST_SUBTEST_PASS();

    /* Verify STATUS.DRBG_READY goes high when stream has data (use prefetch to observe it) */
    TEST_SUBTEST_START("DRBG STATUS.DRBG_READY observed");
    DRBG_CFG_REG.f.prefetch = 1;
    test_delay(5);
    {
        uint32_t i;
        const uint32_t max_poll = 5000u;
        for (i = 0; i < max_poll; i++) {
            if (DRBG_STATUS_REG.f.drbg_ready != 0) {
                break;
            }
            test_delay(1);
        }
        if (i >= max_poll) {
            TEST_FAIL("STATUS.DRBG_READY not set after %u polls", (unsigned)max_poll);
        }
        (void)DRBG_DATA_REG.f.data; /* consume prefetched word */
    }
    DRBG_CFG_REG.f.prefetch = 0;
    TEST_SUBTEST_PASS();

    /* Retrieve random data: get scheduled next (random), read DATA, verify match */
    TEST_SUBTEST_START("DRBG DATA read matches TB random");
    if (!tb_drbg_get_next_value(&expected, 1000)) {
        TEST_FAIL("tb_drbg_get_next_value failed");
    }
    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, expected, "DRBG DATA random");
    TEST_LOG("  Read 0x%08X, expected (random) 0x%08X", read_val, expected);
    TEST_SUBTEST_PASS();

    /* Override next value, get expected (scheduled next), read DATA, verify */
    TEST_SUBTEST_START("DRBG DATA read matches TB override");
    if (!tb_drbg_set_next_value(0xDEADBEEF, 1000)) {
        TEST_FAIL("tb_drbg_set_next_value failed");
    }
    if (!tb_drbg_get_next_value(&expected, 1000)) {
        TEST_FAIL("tb_drbg_get_next_value failed");
    }
    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, expected, "DRBG DATA");
    TEST_LOG("  Read 0x%08X, expected 0x%08X", read_val, expected);
    TEST_SUBTEST_PASS();

    /* Second read: override again, get expected, read, verify */
    TEST_SUBTEST_START("DRBG DATA second read");
    if (!tb_drbg_set_next_value(0xCAFEBABE, 1000)) {
        TEST_FAIL("tb_drbg_set_next_value (2) failed");
    }
    if (!tb_drbg_get_next_value(&expected, 1000)) {
        TEST_FAIL("tb_drbg_get_next_value (2) failed");
    }
    read_val = DRBG_DATA_REG.f.data;
    TEST_ASSERT_EQ(read_val, expected, "DRBG DATA second");
    TEST_SUBTEST_PASS();

    /* Verify COUNT_GOOD was incremented at least once for successful DATA reads */
    if (DRBG_STATUS_REG.f.count_good == 0u) {
        TEST_FAIL("STATUS.COUNT_GOOD not incremented after successful reads");
    }

    TEST_PASS();
    return 0;
}
