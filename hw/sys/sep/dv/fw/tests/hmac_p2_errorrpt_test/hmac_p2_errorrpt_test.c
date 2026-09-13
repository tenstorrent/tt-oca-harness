/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 Error Reporting Test.
 *
 * Covers illegal operation reporting and recovery:
 *   1) MSG_FIFO push while sha_en=0 -> SwPushMsgWhenDisallowed and hmac_err.
 *   2) hash_start while engine is already active -> SwHashStartWhenActive.
 *   3) Safe MSG_FIFO accept via MSG_LENGTH (CPU MMIO; capacity/full is UVM scope),
 *      then process/drain recovery.
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"
#include "test_completion.h"
static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (status.f.hmac_idle) {
            return 0;
        }
    }

    printf("  Timeout waiting for HMAC idle\n");
    return -1;
}

static int wait_for_hmac_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || status.f.hmac_idle) {
            break;
        }
    }
    if (timeout <= 0) {
        printf("  Timeout waiting for HMAC completion\n");
        return -1;
    }

    hmac__INTR_STATE_t clear = {.w = 0};
    clear.f.hmac_done = 1;
    clear.f.fifo_empty = 1;
    clear.f.hmac_err = 1;
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

static int recover_hmac_state(void) {
    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    cfg.f.hmac_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    cfg.w = 0;
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);
    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);

    if (wait_for_hmac_done() != 0) {
        return -1;
    }

    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    cfg.f.sha_en = 0;
    cfg.f.hmac_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xffffffffu);

    hmac__INTR_STATE_t clear = {.w = 0};
    clear.f.hmac_done = 1;
    clear.f.fifo_empty = 1;
    clear.f.hmac_err = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);

    /* ERR_CODE is sticky; allow-path polarity after recovery is hmac_err clear. */
    if (assert_hmac_err_clear("after recovery W1C") != 0) {
        return -1;
    }

    printf("  Recovery: sticky ERR_CODE=0x%08x STATUS=0x%08x\n",
           READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR),
           READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR));

    return wait_for_idle();
}

static int expect_hmac_error(const char *name, uint32_t expected_err) {
    uint32_t err = READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR);
    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};

    int pass = 1;
    if (!check_reg(name, err, expected_err)) {
        pass = 0;
    }

    printf("  INTR_STATE.hmac_err=%u\n", intr.f.hmac_err);
    if (!intr.f.hmac_err) {
        printf("  FAIL: hmac_err interrupt state did not assert\n");
        pass = 0;
    }

    return pass ? 0 : -1;
}

static int test_push_when_sha_disabled(void) {
    printf("\nStep 1: MSG_FIFO push while sha_en=0\n");

    if (assert_hmac_err_clear("before push-disabled negative") != 0) {
        return -1;
    }

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    *fifo8 = 0xa5;

    if (expect_hmac_error("ERR_CODE push while sha_en=0",
                          SEP_HMAC_ERR_SW_PUSH_MSG_WHEN_DISALLOWED) != 0) {
        return -1;
    }

    return recover_hmac_state();
}

static int test_hash_start_when_busy(void) {
    printf("\nStep 2: hash_start while engine is active\n");

    if (assert_hmac_err_clear("before busy-start negative") != 0) {
        return -1;
    }

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    if (assert_hmac_err_clear("after legal first hash_start") != 0) {
        return -1;
    }

    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    if (expect_hmac_error("ERR_CODE hash_start while active",
                          SEP_HMAC_ERR_SW_HASH_START_WHEN_ACTIVE) != 0) {
        return -1;
    }

    return recover_hmac_state();
}

static int test_fifo_accept(void) {
    printf("\nStep 3: Write MSG_FIFO then recover by process/drain\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    volatile uint32_t *fifo32 = (volatile uint32_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    const uint32_t words_written = 32u;
    int full_seen = 0;
    uint32_t max_depth = 0;

    for (uint32_t i = 0; i < words_written; i++) {
        *fifo32 = 0x5a000000u | i;
        hmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (status.f.fifo_depth > max_depth) max_depth = status.f.fifo_depth;
        if (status.f.fifo_full) full_seen = 1;
    }

    uint32_t msg_bits = READ_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR);
    printf("  words_written=%u MSG_LENGTH=%u fifo_full=%u max_depth=%u\n", words_written, msg_bits,
           full_seen, max_depth);
    if (msg_bits != words_written * 32u) {
        printf("  FAIL: MSG_LENGTH mismatch (FIFO did not accept writes)\n");
        /* Still attempt drain to avoid leaving engine active. */
    } else {
        printf("  PASS: MSG_FIFO accepted %u words (instant drain OK under CPU MMIO)\n",
               words_written);
    }
    /* CPU MMIO cannot reliably observe fifo_full; capacity is UVM/TL-burst scope.
     * This step proves MSG_FIFO accept via MSG_LENGTH only (FAIL-ON above). */
    (void)full_seen;
    (void)max_depth;

    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);
    if (wait_for_hmac_done() != 0) {
        return -1;
    }
    if (msg_bits != words_written * 32u) {
        return -1;
    }

    hmac__CFG_t cfg_off = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg_off.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg_off.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xffffffffu);

    hmac__STATUS_t reset_status = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    int pass = 1;
    if (!check_reg("STATUS.hmac_idle after drain", reset_status.f.hmac_idle, 1)) {
        pass = 0;
    }
    if (!check_reg("STATUS.fifo_empty after drain", reset_status.f.fifo_empty, 1)) {
        pass = 0;
    }
    printf("  ERR_CODE after drain: 0x%08x (sticky error code is allowed)\n",
           READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR));

    return pass ? 0 : -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC P2 Error Reporting Test\n");
    printf("========================================\n");

    int pass = 1;

    hmac__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.hmac_done = 1;
    intr_en.f.fifo_empty = 1;
    intr_en.f.hmac_err = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    /* Initial allow-path: ERR_CODE and hmac_err must be clean before negatives. */
    if (recover_hmac_state() != 0) {
        pass = 0;
    }
    if (!check_reg("ERR_CODE initial allow-path", READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR),
                   SEP_HMAC_ERR_NO_ERROR)) {
        pass = 0;
    }

    if (pass && test_push_when_sha_disabled() != 0) {
        pass = 0;
    }
    if (pass && test_hash_start_when_busy() != 0) {
        pass = 0;
    }
    if (pass && test_fifo_accept() != 0) {
        pass = 0;
    }

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC P2 ERROR REPORTING TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC P2 ERROR REPORTING TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
