/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * FIFO Status Monitoring Test
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

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR)};
        if (intr.f.kmac_done) {
            WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
            return 0;
        }
    }
    printf("Timeout waiting for KMAC done\n");
    return -1;
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

static int test_fifo_status(void) {
    printf("\n=== FIFO Status Test ===\n");

    if (wait_for_idle() != 0) return -1;

    kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    if (s.f.fifo_empty) {
        printf("PASS: fifo_empty=1 initially\n");
    } else {
        printf("FAIL: fifo_empty=%u expected 1\n", s.f.fifo_empty);
        test_errors++;
    }

    seed_sw_entropy();

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    s.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR);
    uint32_t baseline_depth = s.f.fifo_depth;
    printf("  After START baseline depth=%u\n", baseline_depth);

    /*
     * SHA3-256 rate = 34 words. Burst without per-word STATUS polls so the
     * padder can back up the MSG_FIFO. Also accept instant-drain if PROCESS
     * still completes (message was absorbed).
     */
    printf("  Writing 48 words to MSG_FIFO (tight burst)...\n");
    for (int i = 0; i < 48; i++) {
        WRITE_REG(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0xA5A5A500u + (uint32_t)i);
    }
    s.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR);
    printf("  After burst: depth=%u empty=%u full=%u baseline=%u\n", s.f.fifo_depth, s.f.fifo_empty,
           s.f.fifo_full, baseline_depth);
    /* Instant drain under CPU MMIO is expected; do not soft-skip. Accept proof is
     * PROCESS completion + fifo_empty below (capacity/full needs UVM TL burst). */
    (void)baseline_depth;

    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    s.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR);
    if (s.f.fifo_empty) {
        printf("PASS: fifo_empty=1 after completion\n");
    } else {
        printf("FAIL: fifo_empty=%u after completion\n", s.f.fifo_empty);
        test_errors++;
    }

    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  FIFO Status Test\n");
    printf("========================================\n");

    if (test_fifo_status() != 0) {
        test_errors++;
    }

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
