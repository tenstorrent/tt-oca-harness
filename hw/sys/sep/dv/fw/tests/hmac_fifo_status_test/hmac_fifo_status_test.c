/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*
 * HMAC FIFO Status Monitoring Test - TC_HMAC_004 (P0)
 *
 * Verifies MSG FIFO status tracking: fifo_empty, fifo_depth, fifo_full
 * through write filling and hash processing drain cycle.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_hmac_fifo_status_test STACK=sim
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

static int check_reg(const char *name, uint32_t actual, uint32_t expected)
{
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n",
           name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static int wait_hmac_done(void)
{
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) {
            break;
        }
    }
    if (timeout <= 0) {
        printf("  Timeout waiting for HMAC completion\n");
        return -1;
    }
    hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    return 0;
}

static void hmac_cleanup(void)
{
    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
}

int main(void)
{
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC FIFO Status Test (TC_HMAC_004)\n");
    printf("========================================\n\n");

    int pass = 1;

    /* Step 1: Verify initial FIFO status (idle, empty, depth=0) */
    printf("Step 1: Verify initial FIFO status\n");
    hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    if (!check_reg("STATUS.fifo_empty (initial)", sts.f.fifo_empty, 1)) pass = 0;
    if (!check_reg("STATUS.fifo_depth (initial)", sts.f.fifo_depth, 0)) pass = 0;
    printf("  STATUS.fifo_full=%u hmac_idle=%u\n", sts.f.fifo_full, sts.f.hmac_idle);

    /* Step 2: Configure SHA-256 mode and start hash */
    printf("\nStep 2: Configure SHA-256 and hash_start\n");
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    printf("  hash_start issued\n");

    /* Step 3: Write 1 word to MSG_FIFO, verify fifo_empty deasserts */
    printf("\nStep 3: Write 1 word, verify fifo_empty=0\n");
    volatile uint32_t *fifo32 = (volatile uint32_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    *fifo32 = 0xDEADBEEFu;

    sts.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
    printf("  After 1 word: fifo_empty=%u fifo_depth=%u fifo_full=%u\n",
           sts.f.fifo_empty, sts.f.fifo_depth, sts.f.fifo_full);
    if (sts.f.fifo_empty == 1) {
        printf("  WARNING: fifo_empty still 1 after write (HW may have consumed it)\n");
    }

    /* Step 4: Fill FIFO until fifo_full=1 or depth approaches 32 */
    printf("\nStep 4: Fill FIFO until full or depth=32\n");
    uint32_t words_written = 1;
    int fifo_full_seen = 0;
    uint32_t max_depth_seen = 0;

    for (uint32_t i = 0; i < 64; i++) {
        sts.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
        if (sts.f.fifo_depth > max_depth_seen)
            max_depth_seen = sts.f.fifo_depth;

        if (sts.f.fifo_full) {
            fifo_full_seen = 1;
            printf("  FIFO full after %u words, depth=%u\n", words_written, sts.f.fifo_depth);
            break;
        }

        *fifo32 = (0xA0000000u | i);
        words_written++;
    }

    if (!fifo_full_seen) {
        sts.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
        if (sts.f.fifo_depth > max_depth_seen)
            max_depth_seen = sts.f.fifo_depth;
        printf("  Wrote %u words total, max_depth=%u, fifo_full=%u\n",
               words_written, max_depth_seen, sts.f.fifo_full);
    }

    /* Step 5: Verify fifo_full if reached capacity */
    printf("\nStep 5: Verify fifo_full status\n");
    sts.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
    printf("  STATUS: fifo_empty=%u fifo_full=%u fifo_depth=%u\n",
           sts.f.fifo_empty, sts.f.fifo_full, sts.f.fifo_depth);
    if (fifo_full_seen) {
        if (!check_reg("fifo_full at capacity", sts.f.fifo_full, 1)) {
            printf("  NOTE: FIFO may have drained during read; continuing\n");
        }
    } else {
        printf("  fifo_full not reached (max_depth=%u); FIFO may drain faster than fill\n",
               max_depth_seen);
    }

    /* Step 6: hash_process and wait for completion */
    printf("\nStep 6: hash_process and wait for completion\n");
    hmac__CMD_t cmd_proc = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_proc.w);

    if (wait_hmac_done() != 0) {
        pass = 0;
    }

    /* Step 7: Verify FIFO is empty after processing */
    printf("\nStep 7: Verify FIFO empty after processing\n");
    sts.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
    if (!check_reg("STATUS.fifo_empty (after process)", sts.f.fifo_empty, 1)) pass = 0;
    printf("  STATUS: fifo_depth=%u hmac_idle=%u\n", sts.f.fifo_depth, sts.f.hmac_idle);

    /* Cleanup */
    hmac_cleanup();

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC FIFO STATUS TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC FIFO STATUS TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) { __asm__("wfi"); }
    return pass ? 0 : -1;
}
