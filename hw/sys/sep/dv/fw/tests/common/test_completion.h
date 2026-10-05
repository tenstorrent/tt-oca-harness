/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Test completion protocol for SEP firmware tests.
//
// This header is intended for C/C++ only (do not include from assembly).
// It writes a 2-word magic sequence to STDOUT (internal mailbox) using 32-bit stores,
// which the SV testbench interprets as PASS/FAIL without colliding with ASCII output.
//
// Sequence (write twice to STDOUT address):
//   1) TEST_MAGIC0
//   2) TEST_MAGIC_PASS or TEST_MAGIC_FAIL

#ifndef SEP_TEST_COMPLETION_H
#define SEP_TEST_COMPLETION_H

// Magic constants defined in tb.h for sharing with assembly (crt0.s)
#include "tb.h"

static inline void test_pass(int code) {
    (void)code;
    volatile unsigned int *stdout_w = (volatile unsigned int *)STDOUT;
    *stdout_w = (unsigned int)TEST_MAGIC0;
    __asm__ volatile("fence" ::: "memory"); // Ensure first write completes
    *stdout_w = (unsigned int)TEST_MAGIC_PASS;
}

static inline void test_fail(int code) {
    (void)code;
    volatile unsigned int *stdout_w = (volatile unsigned int *)STDOUT;
    *stdout_w = (unsigned int)TEST_MAGIC0;
    __asm__ volatile("fence" ::: "memory"); // Ensure first write completes
    *stdout_w = (unsigned int)TEST_MAGIC_FAIL;
}

#endif // SEP_TEST_COMPLETION_H
