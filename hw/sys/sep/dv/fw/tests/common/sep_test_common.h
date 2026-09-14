/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Test Common Header
 * Common definitions for all SEP fabric tests
 */

#ifndef SEP_TEST_COMMON_H
#define SEP_TEST_COMMON_H

#include <stdint.h>
#include <stdio.h>

// Test status definitions
#define TEST_PASS 0
#define TEST_FAIL -1

// Common test macros
#define ASSERT(cond) \
    do { \
        if (!(cond)) { \
            printf("ASSERTION FAILED: %s at %s:%d\n", #cond, __FILE__, __LINE__); \
            return TEST_FAIL; \
        } \
    } while (0)

#define CHECK_RESULT(result) \
    do { \
        if ((result) != 0) { \
            printf("TEST FAILED at %s:%d\n", __FILE__, __LINE__); \
            return TEST_FAIL; \
        } \
    } while (0)

// Test utility functions
static inline void test_delay_us(uint32_t us) {
    for (volatile uint32_t i = 0; i < us * 10; i++) {
        __asm__ __volatile__("nop");
    }
}

static inline void test_log(const char *msg) {
    printf("[TEST] %s\n", msg);
}

// Test completion helpers
static inline void test_pass(const char *test_name) {
    printf("✅ PASS: %s\n", test_name);
}

static inline void test_fail(const char *test_name) {
    printf("❌ FAIL: %s\n", test_name);
}

#endif // SEP_TEST_COMMON_H
