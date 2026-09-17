/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC Error Detection Test
 *
 * Verifies ERR_CODE reporting for three error conditions plus a clean-path
 * positive control before each negative:
 * - Push MSG_FIFO when sha_en=0 -> SwPushMsgWhenDisallowed
 * - hash_start when sha_en=0 -> SwHashStartWhenShaDisabled
 * - second hash_start while active -> SwHashStartWhenActive
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static int wait_hmac_done(void) {
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

static int assert_hmac_err_clear(const char *tag) {
    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.hmac_err) {
        printf("  FAIL: %s hmac_err still set\n", tag);
        return -1;
    }
    printf("  %s hmac_err=0 - PASS\n", tag);
    return 0;
}

static int hmac_reset_via_hash(void) {
    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    hmac__CMD_t cmd_proc = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_proc.w);

    if (wait_hmac_done() != 0) return -1;

    hmac__INTR_STATE_t clr_all = {.w = 0};
    clr_all.f.hmac_done = 1;
    clr_all.f.fifo_empty = 1;
    clr_all.f.hmac_err = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clr_all.w);

    /*
     * ERR_CODE is sticky (RO/HWO). Allow-path control after recovery is
     * hmac_err clear + legal empty hash must not re-assert hmac_err.
     */
    if (assert_hmac_err_clear("after recovery W1C") != 0) {
        return -1;
    }
    printf("  Sticky ERR_CODE after recovery: 0x%08x\n",
           READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR));
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC Error Handling Test\n");
    printf("========================================\n\n");

    int pass = 1;

    /* Positive control before first negative: ERR_CODE and hmac_err must be clean. */
    printf("Step 0: Clean allow-path control (initial)\n");
    if (hmac_reset_via_hash() != 0) {
        printf("  Allow-path control failed\n");
        pass = 0;
    }
    if (!check_reg("ERR_CODE initial allow-path", READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR),
                   SEP_HMAC_ERR_NO_ERROR)) {
        pass = 0;
    }

    /* ---------------------------------------------------------- */
    /* Error 1: Push MSG_FIFO when sha_en=0 */
    /* ---------------------------------------------------------- */
    printf("\nStep 1: Push MSG_FIFO when sha_en=0 (expect SwPushMsgWhenDisallowed)\n");

    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    *fifo8 = 0xAA;

    uint32_t err = READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR);
    if (!check_reg("ERR_CODE (push when sha_en=0)", err,
                   SEP_HMAC_ERR_SW_PUSH_MSG_WHEN_DISALLOWED)) {
        pass = 0;
    }

    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (!intr.f.hmac_err) {
        printf("  FAIL: hmac_err did not assert\n");
        pass = 0;
    } else {
        printf("  INTR_STATE.hmac_err=1 - PASS\n");
    }

    printf("  Resetting HMAC block...\n");
    if (hmac_reset_via_hash() != 0) {
        printf("  Reset / allow-path failed\n");
        pass = 0;
    }

    /* ---------------------------------------------------------- */
    /* Error 2: SwHashStartWhenShaDisabled */
    /* ---------------------------------------------------------- */
    printf("\nStep 2: SwHashStartWhenShaDisabled\n");

    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    err = READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR);
    if (!check_reg("ERR_CODE (SwHashStartWhenShaDisabled)", err,
                   SEP_HMAC_ERR_SW_HASH_START_WHEN_SHA_DISABLED)) {
        pass = 0;
    }

    intr.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!intr.f.hmac_err) {
        printf("  FAIL: hmac_err did not assert\n");
        pass = 0;
    } else {
        printf("  INTR_STATE.hmac_err=1 - PASS\n");
    }

    printf("  Resetting HMAC block...\n");
    if (hmac_reset_via_hash() != 0) {
        printf("  Reset / allow-path failed\n");
        pass = 0;
    }

    /* ---------------------------------------------------------- */
    /* Error 3: SwHashStartWhenActive */
    /* ---------------------------------------------------------- */
    printf("\nStep 3: SwHashStartWhenActive\n");

    cfg.w = 0;
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    cmd.w = 0;
    cmd.f.hash_start = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    /* Allow-path after first start: legal op must not assert hmac_err. */
    if (assert_hmac_err_clear("after legal first hash_start") != 0) {
        pass = 0;
    }

    cmd.w = 0;
    cmd.f.hash_start = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    err = READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR);
    if (!check_reg("ERR_CODE (SwHashStartWhenActive)", err,
                   SEP_HMAC_ERR_SW_HASH_START_WHEN_ACTIVE)) {
        pass = 0;
    }

    intr.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!intr.f.hmac_err) {
        printf("  FAIL: hmac_err did not assert\n");
        pass = 0;
    } else {
        printf("  INTR_STATE.hmac_err=1 - PASS\n");
    }

    printf("  Final cleanup: hash_process and wait...\n");
    hmac__CMD_t cmd_proc = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_proc.w);
    if (wait_hmac_done() != 0) {
        printf("  Final cleanup wait failed\n");
        pass = 0;
    }

    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

    hmac__INTR_STATE_t clr_all = {.w = 0};
    clr_all.f.hmac_done = 1;
    clr_all.f.fifo_empty = 1;
    clr_all.f.hmac_err = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clr_all.w);

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC ERROR HANDLING TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC ERROR HANDLING TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
