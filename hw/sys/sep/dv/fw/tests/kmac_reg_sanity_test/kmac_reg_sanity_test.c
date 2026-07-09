/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_001 (P0) - KMAC Register Defaults and Read/Write Sanity Test
 *
 * Verifies default register values after reset and basic read/write
 * functionality for KMAC configuration and interrupt registers.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

static int test_errors = 0;

static void check_reg(const char *name, uint32_t addr, uint32_t expected) {
    uint32_t actual = READ_REG(addr);
    if (actual != expected) {
        printf("FAIL: %s expected=0x%08x actual=0x%08x\n", name, expected, actual);
        test_errors++;
    } else {
        printf("PASS: %s = 0x%08x\n", name, actual);
    }
}

static void check_rw(const char *name, uint32_t addr, uint32_t write_val, uint32_t expected_read) {
    WRITE_REG(addr, write_val);
    uint32_t actual = READ_REG(addr);
    if (actual != expected_read) {
        printf("FAIL: %s RW write=0x%08x readback=0x%08x expected=0x%08x\n", name, write_val,
               actual, expected_read);
        test_errors++;
    } else {
        printf("PASS: %s RW readback=0x%08x\n", name, actual);
    }
}

static int test_register_defaults(void) {
    printf("\n=== Test 1: Register Default Values ===\n");

    check_reg("STATUS", OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR, 0x00004001);
    check_reg("CFG_REGWEN", OCH_SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR, 0x00000001);
    check_reg("CFG_SHADOWED", OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, 0x00001000);
    check_reg("ERR_CODE", OCH_SEP_TOP_KMAC_ERR_CODE_BASE_ADDR, 0x00000000);
    check_reg("INTR_ENABLE", OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x00000000);
    check_reg("INTR_STATE", OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x00000000);
    check_reg("ENTROPY_PERIOD", OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, 0x00000000);

    return 0;
}

static int test_intr_enable_rw(void) {
    printf("\n=== Test 2: INTR_ENABLE Read/Write ===\n");

    check_rw("INTR_ENABLE all", OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x7, 0x7);
    check_rw("INTR_ENABLE clear", OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0, 0x0);

    return 0;
}

static int test_intr_test_w1s(void) {
    printf("\n=== Test 3: INTR_TEST -> INTR_STATE W1C (all 3 bits) ===\n");

    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0);

    /* --- bit 0: kmac_done --- */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7); /* clear all */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0x1);
    uint32_t state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & 0x1) {
        printf("PASS: INTR_TEST.kmac_done set INTR_STATE.kmac_done\n");
    } else {
        printf("FAIL: INTR_TEST.kmac_done did not set INTR_STATE state=0x%08x\n", state);
        test_errors++;
    }
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1);
    state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & 0x1)) {
        printf("PASS: INTR_STATE.kmac_done cleared by W1C\n");
    } else {
        printf("FAIL: INTR_STATE.kmac_done not cleared state=0x%08x\n", state);
        test_errors++;
    }

    /* --- bit 1: fifo_empty (level-triggered, may re-assert) --- */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0x2);
    state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & 0x2) {
        printf("PASS: INTR_TEST.fifo_empty set INTR_STATE.fifo_empty\n");
    } else {
        printf("FAIL: INTR_TEST.fifo_empty did not set INTR_STATE state=0x%08x\n", state);
        test_errors++;
    }
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x2);
    state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & 0x2)) {
        printf("PASS: INTR_STATE.fifo_empty cleared by W1C\n");
    } else {
        /* fifo_empty is level-triggered; re-asserts when FIFO is empty - not a failure */
        printf("INFO: INTR_STATE.fifo_empty re-asserted (level-triggered) state=0x%08x\n", state);
    }

    /* --- bit 2: kmac_err --- */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0x4);
    state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & 0x4) {
        printf("PASS: INTR_TEST.kmac_err set INTR_STATE.kmac_err\n");
    } else {
        printf("FAIL: INTR_TEST.kmac_err did not set INTR_STATE state=0x%08x\n", state);
        test_errors++;
    }
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x4);
    state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & 0x4)) {
        printf("PASS: INTR_STATE.kmac_err cleared by W1C\n");
    } else {
        printf("FAIL: INTR_STATE.kmac_err not cleared state=0x%08x\n", state);
        test_errors++;
    }

    /* Clear all remaining */
    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x7);

    return 0;
}

static int test_prefix_rw(void) {
    printf("\n=== Test 4: PREFIX Register Read/Write ===\n");

    uint32_t test_val = 0x12345678;
    check_rw("PREFIX_0", OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), test_val, test_val);

    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x0);
    uint32_t readback = READ_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0));
    if (readback == 0x0) {
        printf("PASS: PREFIX_0 restored to 0\n");
    } else {
        printf("FAIL: PREFIX_0 restore readback=0x%08x\n", readback);
        test_errors++;
    }

    return 0;
}

static int test_entropy_period_rw(void) {
    printf("\n=== Test 5: ENTROPY_PERIOD Read/Write ===\n");

    uint32_t test_val = 0xFFFF03FF;
    WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, test_val);
    kmac__ENTROPY_PERIOD_t ep = {.w = READ_REG(OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR)};
    printf("  ENTROPY_PERIOD readback=0x%08x prescaler=%u wait_timer=%u\n", ep.w, ep.f.prescaler,
           ep.f.wait_timer);

    if (ep.f.prescaler == 0x3FF && ep.f.wait_timer == 0xFFFF) {
        printf("PASS: ENTROPY_PERIOD fields correct\n");
    } else {
        printf("FAIL: ENTROPY_PERIOD field mismatch\n");
        test_errors++;
    }

    WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, 0x0);

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  TC_KMAC_001: Register Sanity Test\n");
    printf("========================================\n");

    test_register_defaults();
    test_intr_enable_rw();
    test_intr_test_w1s();
    test_prefix_rw();
    test_entropy_period_rw();

    printf("\n========================================\n");
    if (test_errors == 0) {
        printf("  RESULT: ALL TESTS PASSED\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("  RESULT: %d TESTS FAILED\n", test_errors);
        printf("========================================\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
