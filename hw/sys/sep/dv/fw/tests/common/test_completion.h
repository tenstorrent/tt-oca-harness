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

#include <stdint.h>

// Magic constants defined in tb.h for sharing with assembly (crt0.s)
#include "tb.h"

// Claims serviced by the crt0.s default handler, i.e. interrupts with no
// registered handler. Weak, so an image without crt0.s still links.
extern volatile uint32_t sep_dummy_int_count __attribute__((weak));

static inline void test_pass(int code) {
    (void)code;
    volatile unsigned int *stdout_w = (volatile unsigned int *)STDOUT;
    // An unhandled interrupt fails the test, the same rule as a main() return.
    // Interrupts are masked first, so the count read here is final for the verdict.
    __asm__ volatile("csrc mstatus, %0" ::"r"(1u << 3) : "memory"); // mstatus.mie
    int unhandled = (&sep_dummy_int_count != 0) && (sep_dummy_int_count != 0);
    *stdout_w = (unsigned int)TEST_MAGIC0;
    __asm__ volatile("fence" ::: "memory"); // Ensure first write completes
    *stdout_w = (unsigned int)(unhandled ? TEST_MAGIC_FAIL : TEST_MAGIC_PASS);
}

static inline void test_fail(int code) {
    (void)code;
    volatile unsigned int *stdout_w = (volatile unsigned int *)STDOUT;
    *stdout_w = (unsigned int)TEST_MAGIC0;
    __asm__ volatile("fence" ::: "memory"); // Ensure first write completes
    *stdout_w = (unsigned int)TEST_MAGIC_FAIL;
}

#endif // SEP_TEST_COMPLETION_H
