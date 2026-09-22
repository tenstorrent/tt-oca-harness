/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Error Detection Test
 *
 * Tests:
 * 1. ErrSwPushedMsgFifo: Write MSG_FIFO without START
 * 2. ErrSwCmdSequence: Issue PROCESS without START
 * Verifies packed ERR_CODE [31:24] and clears via CMD.err_processed.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static void clear_error(void) {
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.err_processed = 1;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                     KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                     KMAC__INTR_STATE__KMAC_ERR_bm);
}

static int assert_allow_path(const char *tag) {
    /* OT: ERR_CODE is sticky and is NOT cleared by err_processed / INTR W1C. */
    kmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    uint32_t err = READ_REG(SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
    if (intr.f.kmac_err) {
        printf("  FAIL: %s allow-path dirty kmac_err=1 (ERR_CODE=0x%08x sticky OK)\n", tag, err);
        return -1;
    }
    printf("  %s allow-path clean (kmac_err=0, sticky ERR_CODE=0x%08x) - PASS\n", tag, err);
    return 0;
}

static void seed_sw_entropy(void) {
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEFu + (uint32_t)i);
    }
}

static int expect_err_code(const char *name, uint32_t expected_code) {
    uint32_t err = READ_REG(SEP_TOP_KMAC_ERR_CODE_BASE_ADDR);
    uint32_t code = SEP_KMAC_ERR_CODE_BYTE(err);
    kmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
    printf("  %s ERR_CODE=0x%08x code=0x%02x expected=0x%02x kmac_err=%u\n", name, err, code,
           expected_code, intr.f.kmac_err);

    int ok = 1;
    if (code != expected_code) {
        printf("  FAIL: ERR_CODE byte mismatch\n");
        ok = 0;
    }
    if (!intr.f.kmac_err) {
        printf("  FAIL: kmac_err did not assert\n");
        ok = 0;
    }
    return ok ? 0 : -1;
}

static int test_err_sw_pushed_msg_fifo(void) {
    printf("\n=== Test ErrSwPushedMsgFifo ===\n");

    if (wait_for_idle() != 0) return -1;
    clear_error();
    if (assert_allow_path("before MSG_FIFO negative") != 0) return -1;

    seed_sw_entropy();

    WRITE_REG(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0xDEADBEEF);
    printf("  Wrote MSG_FIFO without START\n");

    if (expect_err_code("ErrSwPushedMsgFifo", SEP_KMAC_ERR_SW_PUSHED_MSG_FIFO) != 0) {
        return -1;
    }

    clear_error();
    if (wait_for_idle() != 0) return -1;
    return 0;
}

static int test_err_sw_cmd_sequence(void) {
    printf("\n=== Test ErrSwCmdSequence ===\n");

    if (wait_for_idle() != 0) return -1;
    clear_error();
    if (assert_allow_path("before PROCESS negative") != 0) return -1;

    seed_sw_entropy();

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  Issued PROCESS without START\n");

    if (expect_err_code("ErrSwCmdSequence", SEP_KMAC_ERR_SW_CMD_SEQUENCE) != 0) {
        return -1;
    }

    clear_error();
    if (wait_for_idle() != 0) return -1;
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  Error Handling Test\n");
    printf("========================================\n");

    if (test_err_sw_pushed_msg_fifo() != 0) test_errors++;
    if (test_err_sw_cmd_sequence() != 0) test_errors++;

    printf("\n========================================\n");
    if (test_errors == 0) {
        printf("  RESULT: ALL TESTS PASSED\n");
        test_pass(0);
    } else {
        printf("  RESULT: %d TESTS FAILED\n", test_errors);
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
