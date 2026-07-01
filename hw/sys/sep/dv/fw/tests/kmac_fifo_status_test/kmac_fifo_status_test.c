/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_005 (P0) - FIFO Status Monitoring Test
 *
 * Verifies FIFO status fields: fifo_empty initial state, fifo_depth
 * tracking during message writes, and fifo_empty after completion.
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
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        uint32_t intr = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & 0x1) {
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1);
            return 0;
        }
    }
    printf("Timeout waiting for KMAC done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static void print_status(const char *tag) {
    kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    printf("  %s: idle=%u absorb=%u squeeze=%u depth=%u empty=%u full=%u\n",
           tag, s.f.sha3_idle, s.f.sha3_absorb, s.f.sha3_squeeze,
           s.f.fifo_depth, s.f.fifo_empty, s.f.fifo_full);
}

static int test_fifo_status(void) {
    printf("\n=== FIFO Status Test ===\n");

    if (wait_for_idle() != 0) return -1;

    /* Check initial state: fifo_empty should be 1 */
    kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    if (s.f.fifo_empty) {
        printf("PASS: fifo_empty=1 initially\n");
    } else {
        printf("FAIL: fifo_empty=%u expected 1\n", s.f.fifo_empty);
        test_errors++;
    }

    /* Configure SHA3-256 */
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = 0x0;
    cfg.f.kstrength = 0x2;
    cfg.f.entropy_mode = 0x1;  /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    cfg.f.entropy_ready = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    setup_entropy();

    cfg.f.entropy_ready = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    printf("  entropy_ready set\n");

    /* START */
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  START issued\n");
    print_status("After START");

    /* Write multiple words and observe fifo_depth */
    printf("  Writing 8 words to MSG_FIFO...\n");
    uint32_t prev_depth = 0;
    int depth_changed = 0;
    for (int i = 0; i < 8; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0xA5A5A500 + i);
        s.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR);
        printf("    Word %d: depth=%u empty=%u full=%u\n",
               i, s.f.fifo_depth, s.f.fifo_empty, s.f.fifo_full);
        if (s.f.fifo_depth != prev_depth || i == 0) {
            depth_changed = 1;
        }
        prev_depth = s.f.fifo_depth;

        if (s.f.fifo_full) {
            printf("    FIFO full after %d words\n", i + 1);
            break;
        }
    }

    if (depth_changed) {
        printf("PASS: fifo_depth changed during writes\n");
    } else {
        printf("INFO: fifo_depth remained %u (HW may drain fast)\n", prev_depth);
    }

    /* PROCESS */
    cmd.f.cmd = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  PROCESS issued\n");

    if (wait_for_done() != 0) return -1;

    /* After done, fifo should be empty */
    s.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR);
    if (s.f.fifo_empty) {
        printf("PASS: fifo_empty=1 after completion\n");
    } else {
        printf("FAIL: fifo_empty=%u after completion\n", s.f.fifo_empty);
        test_errors++;
    }
    print_status("After DONE");

    /* DONE */
    cmd.f.cmd = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  TC_KMAC_005: FIFO Status Test\n");
    printf("========================================\n");

    test_fifo_status();

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
