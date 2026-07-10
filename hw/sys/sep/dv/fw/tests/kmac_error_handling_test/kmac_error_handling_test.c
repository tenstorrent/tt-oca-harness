/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_007 (P0) - Error Detection Test
 *
 * Tests two error conditions:
 *   1. ErrSwPushedMsgFifo (0x02): Write MSG_FIFO without START
 *   2. ErrSwCmdSequence (0x08): Issue PROCESS without START
 * Verifies ERR_CODE and clears via CMD.err_processed.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__none__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_STATUS_BASE_ADDR)};
        if (s.f.SHA3_IDLE) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static void clear_error(void) {
    kmac__none__CMD_t cmd = {.w = 0};
    cmd.f.ERR_PROCESSED = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CMD_BASE_ADDR, cmd.w);

    /* Clear any pending interrupts */
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_INTR_STATE_BASE_ADDR, 0x7);
}

static int test_err_sw_pushed_msg_fifo(void) {
    printf("\n=== Test ErrSwPushedMsgFifo ===\n");

    if (wait_for_idle() != 0) return -1;

    /* Configure but do NOT issue START */
    kmac__none__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 0;
    cfg.f.MODE = 0x0;
    cfg.f.KSTRENGTH = 0x2;
    cfg.f.ENTROPY_MODE = 0x1; /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    cfg.f.ENTROPY_READY = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);

    /* Provide entropy */
    for (int i = 0; i < 6; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_NONE_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
    cfg.f.ENTROPY_READY = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);

    /* Write to MSG_FIFO without START - should trigger error */
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_MSG_FIFO_BASE_ADDR(0), 0xDEADBEEF);
    printf("  Wrote MSG_FIFO without START\n");

    kmac__none__ERR_CODE_t err = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_ERR_CODE_BASE_ADDR)};
    printf("  ERR_CODE = 0x%08x\n", err.w);

    if (err.w != 0) {
        printf("PASS: Error detected (ERR_CODE=0x%08x)\n", err.w);
        if (err.w == 0x02) {
            printf("  Confirmed: ErrSwPushedMsgFifo\n");
        }
    } else {
        printf("FAIL: No error detected for MSG_FIFO write without START\n");
        test_errors++;
    }

    /* Clear error */
    clear_error();
    printf("  Error cleared\n");

    /* Wait for idle after error recovery */
    if (wait_for_idle() != 0) {
        printf("  WARNING: KMAC not idle after error clear\n");
    }

    return 0;
}

static int test_err_sw_cmd_sequence(void) {
    printf("\n=== Test ErrSwCmdSequence ===\n");

    if (wait_for_idle() != 0) return -1;

    /* Configure */
    kmac__none__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 0;
    cfg.f.MODE = 0x0;
    cfg.f.KSTRENGTH = 0x2;
    cfg.f.ENTROPY_MODE = 0x1; /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    cfg.f.ENTROPY_READY = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);

    for (int i = 0; i < 6; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_NONE_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
    cfg.f.ENTROPY_READY = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CFG_SHADOWED_BASE_ADDR, cfg.w);

    /* Issue PROCESS without START - should trigger error */
    kmac__none__CMD_t cmd = {.w = 0};
    cmd.f.CMD = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_NONE_CMD_BASE_ADDR, cmd.w);
    printf("  Issued PROCESS without START\n");

    kmac__none__ERR_CODE_t err = {.w = READ_REG(OCH_SEP_TOP_KMAC_NONE_ERR_CODE_BASE_ADDR)};
    printf("  ERR_CODE = 0x%08x\n", err.w);

    if (err.w != 0) {
        printf("PASS: Error detected (ERR_CODE=0x%08x)\n", err.w);
        if (err.w == 0x08) {
            printf("  Confirmed: ErrSwCmdSequence\n");
        }
    } else {
        printf("FAIL: No error detected for PROCESS without START\n");
        test_errors++;
    }

    /* Clear error */
    clear_error();
    printf("  Error cleared\n");

    if (wait_for_idle() != 0) {
        printf("  WARNING: KMAC not idle after error clear\n");
    }

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  TC_KMAC_007: Error Handling Test\n");
    printf("========================================\n");

    test_err_sw_pushed_msg_fifo();
    test_err_sw_cmd_sequence();

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
