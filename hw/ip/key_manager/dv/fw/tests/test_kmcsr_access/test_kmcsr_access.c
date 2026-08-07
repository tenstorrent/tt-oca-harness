/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kmcsr_access.c
 * @brief KMCSR register access verification test
 *
 * Verifies basic KMCSR register access by reading:
 * - VERSION register (semantic version 1.0.0: major=1, minor=0, patch=0; raw 0x0001_0000)
 * - DEBUG register (should contain magic value 0xCAFEBEEF)
 *
 * Run with:
 *   make run_fw FW_TEST=test_kmcsr_access
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* Register access macros using struct types */
#define KMCSR_VERSION_REG (*(volatile km_csr__version_reg_t *)KEY_MANAGER_KMCSR_VERSION_BASE_ADDR)
#define KMCSR_DEBUG_REG (*(volatile km_csr__debug_reg_t *)KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR)

int main(void) {
    uint32_t version_val;
    uint32_t debug_val;

    TEST_INIT();

    /* Test 1: Read VERSION register (semantic version 1.0.0) */
    TEST_SUBTEST_START("Read VERSION register");
    version_val = KMCSR_VERSION_REG.w;
    TEST_LOG("  VERSION = 0x%08X (expected 0x%08X)", version_val, KMCSR_VERSION_RESET);
    TEST_ASSERT_EQ(version_val, KMCSR_VERSION_RESET, "VERSION raw value");
    TEST_ASSERT_EQ(KMCSR_VERSION_REG.f.major, 1u, "VERSION.MAJOR");
    TEST_ASSERT_EQ(KMCSR_VERSION_REG.f.minor, 0u, "VERSION.MINOR");
    TEST_ASSERT_EQ(KMCSR_VERSION_REG.f.patch, 0u, "VERSION.PATCH");
    TEST_SUBTEST_PASS();

    /* Test 2: Read DEBUG register */
    TEST_SUBTEST_START("Read DEBUG register");
    debug_val = KMCSR_DEBUG_REG.w;
    TEST_LOG("  DEBUG = 0x%08X (expected 0x%08X)", debug_val, KM_CSR__DEBUG_REG__MAGIC_reset);
    TEST_ASSERT_EQ(debug_val, KM_CSR__DEBUG_REG__MAGIC_reset, "DEBUG.MAGIC");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
