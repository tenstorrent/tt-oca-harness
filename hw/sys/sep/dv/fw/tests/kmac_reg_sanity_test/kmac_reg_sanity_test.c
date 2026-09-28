/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC Register Defaults and Read/Write Sanity Test
 *
 * Verifies default register values after reset, basic read/write
 * functionality for KMAC configuration and interrupt registers, and
 * KEY_SHARE write-only read-as-zero behavior.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"

/* Composed from generated field reset / bitmasks in kmac.h. */
#define KMAC_STATUS_RESET_VAL (KMAC__STATUS__SHA3_IDLE_bm | KMAC__STATUS__FIFO_EMPTY_bm)
#define KMAC_CFG_REGWEN_RESET_VAL (KMAC__CFG_REGWEN__EN_bm)
#define KMAC_CFG_SHADOWED_RESET_VAL (KMAC__CFG_SHADOWED__SIDELOAD_bm)

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

static void check_wo_read_zero(const char *name, uint32_t addr, uint32_t write_val) {
    WRITE_REG(addr, write_val);
    uint32_t actual = READ_REG(addr);
    if (actual != 0) {
        printf("FAIL: %s WO write=0x%08x readback=0x%08x expected=0x00000000\n", name, write_val,
               actual);
        test_errors++;
    } else {
        printf("PASS: %s WO readback=0x00000000\n", name);
    }
}

static int test_register_defaults(void) {
    printf("\n=== Test 1: Register Default Values ===\n");

    check_reg("STATUS", SEP_TOP_KMAC_STATUS_BASE_ADDR, KMAC_STATUS_RESET_VAL);
    check_reg("CFG_REGWEN", SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR, KMAC_CFG_REGWEN_RESET_VAL);
    check_reg("CFG_SHADOWED", SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, KMAC_CFG_SHADOWED_RESET_VAL);
    check_reg("ERR_CODE", SEP_TOP_KMAC_ERR_CODE_BASE_ADDR, KMAC__ERR_CODE__ERR_CODE_reset);
    check_reg("INTR_ENABLE", SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0u);
    check_reg("INTR_STATE", SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0u);
    check_reg("ENTROPY_PERIOD", SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, 0u);

    return 0;
}

static int test_intr_enable_rw(void) {
    printf("\n=== Test 2: INTR_ENABLE Read/Write ===\n");

    uint32_t all_intr = KMAC__INTR_ENABLE__KMAC_DONE_bm | KMAC__INTR_ENABLE__FIFO_EMPTY_bm |
                        KMAC__INTR_ENABLE__KMAC_ERR_bm;
    check_rw("INTR_ENABLE all", SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, all_intr, all_intr);
    check_rw("INTR_ENABLE clear", SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0, 0x0);

    return 0;
}

static int test_intr_test_w1s(void) {
    printf("\n=== Test 3: INTR_TEST -> INTR_STATE W1C (all 3 bits) ===\n");

    WRITE_REG(SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, 0x0);

    /* --- bit 0: kmac_done --- */
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                     KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                     KMAC__INTR_STATE__KMAC_ERR_bm); /* clear all */
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_TEST__KMAC_DONE_bm);
    uint32_t state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & KMAC__INTR_STATE__KMAC_DONE_bm) {
        printf("PASS: INTR_TEST.kmac_done set INTR_STATE.kmac_done\n");
    } else {
        printf("FAIL: INTR_TEST.kmac_done did not set INTR_STATE state=0x%08x\n", state);
        test_errors++;
    }
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
    state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & KMAC__INTR_STATE__KMAC_DONE_bm)) {
        printf("PASS: INTR_STATE.kmac_done cleared by W1C\n");
    } else {
        printf("FAIL: INTR_STATE.kmac_done not cleared state=0x%08x\n", state);
        test_errors++;
    }

    /*
     * fifo_empty is Status-type / level. At idle the event is already high, so
     * only claim the set-leg here (INTR_TEST forces the bit). Clear polarity is
     * proven in kmac_interrupt_test with a non-empty FIFO.
     */
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                     KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                     KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_TEST__FIFO_EMPTY_bm);
    state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & KMAC__INTR_STATE__FIFO_EMPTY_bm) {
        printf("PASS: INTR_TEST.fifo_empty set INTR_STATE.fifo_empty\n");
    } else {
        printf("FAIL: INTR_TEST.fifo_empty did not set INTR_STATE state=0x%08x\n", state);
        test_errors++;
    }
    /* Drop vacuous W1C clear claim at idle (level re-assert cannot fail). */
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                     KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                     KMAC__INTR_STATE__KMAC_ERR_bm);

    /* --- bit 2: kmac_err --- */
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                     KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                     KMAC__INTR_STATE__KMAC_ERR_bm);
    WRITE_REG(SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_TEST__KMAC_ERR_bm);
    state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (state & KMAC__INTR_STATE__KMAC_ERR_bm) {
        printf("PASS: INTR_TEST.kmac_err set INTR_STATE.kmac_err\n");
    } else {
        printf("FAIL: INTR_TEST.kmac_err did not set INTR_STATE state=0x%08x\n", state);
        test_errors++;
    }
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_ERR_bm);
    state = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
    if (!(state & KMAC__INTR_STATE__KMAC_ERR_bm)) {
        printf("PASS: INTR_STATE.kmac_err cleared by W1C\n");
    } else {
        printf("FAIL: INTR_STATE.kmac_err not cleared state=0x%08x\n", state);
        test_errors++;
    }

    /* Clear all remaining */
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                     KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                     KMAC__INTR_STATE__KMAC_ERR_bm);

    return 0;
}

static int test_prefix_rw(void) {
    printf("\n=== Test 4: PREFIX Register Read/Write ===\n");

    uint32_t test_val = 0x12345678;
    check_rw("PREFIX_0", SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), test_val, test_val);

    WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x0);
    uint32_t readback = READ_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(0));
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
    WRITE_REG(SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, test_val);
    kmac__ENTROPY_PERIOD_t ep = {.w = READ_REG(SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR)};
    printf("  ENTROPY_PERIOD readback=0x%08x prescaler=%u wait_timer=%u\n", ep.w, ep.f.prescaler,
           ep.f.wait_timer);

    if (ep.f.prescaler == 0x3FF && ep.f.wait_timer == 0xFFFF) {
        printf("PASS: ENTROPY_PERIOD fields correct\n");
    } else {
        printf("FAIL: ENTROPY_PERIOD field mismatch\n");
        test_errors++;
    }

    WRITE_REG(SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, 0x0);

    return 0;
}

static int test_key_share_wo_read_zero(void) {
    printf("\n=== Test 6: KEY_SHARE Write-Only Read-As-Zero ===\n");

    for (uint32_t i = 0; i < SEP_TOP_KMAC_KEY_SHARE0_NUM; i++) {
        char name[32];

        snprintf(name, sizeof(name), "KEY_SHARE0_%u", i);
        check_wo_read_zero(name, SEP_TOP_KMAC_KEY_SHARE0_BASE_ADDR(i),
                           0xa5a50000u | (i * 0x0101u) | i);

        snprintf(name, sizeof(name), "KEY_SHARE1_%u", i);
        check_wo_read_zero(name, SEP_TOP_KMAC_KEY_SHARE1_BASE_ADDR(i),
                           0x5a5a0000u | (i * 0x0101u) | i);
    }

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  Register Sanity Test\n");
    printf("========================================\n");

    test_register_defaults();
    test_intr_enable_rw();
    test_intr_test_w1s();
    test_prefix_rw();
    test_entropy_period_rw();
    test_key_share_wo_read_zero();

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
