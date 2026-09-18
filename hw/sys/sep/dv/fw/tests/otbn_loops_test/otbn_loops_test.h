/* Copyright lowRISC contributors (OpenTitan project). */
/* Licensed under the Apache License, Version 2.0, see LICENSE for details. */
/* SPDX-License-Identifier: Apache-2.0 */
/* Adapted for OCAH platform */

/**
 * @file otbn_loops_test.h
 * @brief OTBN Nested Loops Test Header
 *
 * This test validates OTBN's nested loop functionality by executing:
 * - Outer loop with loopi instruction (4 iterations)
 * - Inner loop with loop instruction (3 iterations each)
 * - Instruction count verification: exactly 28 instructions
 *
 * Test vectors derived from OpenTitan's loops.s test, adapted for OCAH.
 */

#ifndef OTBN_LOOPS_TEST_H
#define OTBN_LOOPS_TEST_H

#include <stdint.h>

/* Expected test results */
#define EXPECTED_INSN_COUNT 28 /* Exact OpenTitan loops.exp instruction count */

/* Note: INSN_CNT is read from CPU-side register, not DMEM */

/* Test status codes */
typedef enum {
    OTBN_LOOPS_TEST_SUCCESS = 0,
    OTBN_LOOPS_TEST_FAIL_INSN_COUNT = 1,
    OTBN_LOOPS_TEST_FAIL_OTBN_ERROR = 2,
    OTBN_LOOPS_TEST_FAIL_TIMEOUT = 3
} otbn_loops_test_result_t;

/* Test function declarations */
otbn_loops_test_result_t otbn_loops_test_run(void);
void otbn_loops_test_print_results(uint32_t insn_count);

#endif /* OTBN_LOOPS_TEST_H */
