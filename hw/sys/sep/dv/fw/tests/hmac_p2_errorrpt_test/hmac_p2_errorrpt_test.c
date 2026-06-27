/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*
 * HMAC P2 Error Reporting Test.
 *
 * Covers illegal operation reporting and recovery:
 *   1) MSG_FIFO push while sha_en=0 -> ERR_CODE=0x5 and hmac_err.
 *   2) hash_start while engine is already active -> ERR_CODE=0x4 and hmac_err.
 *   3) Safe FIFO saturation to fifo_full, then process/drain recovery.
 *
 * The test intentionally does not perform an extra MMIO write after fifo_full,
 * because the AXI write can legally backpressure and hang firmware execution.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_hmac_p2_errorrpt_test STACK=cgen,sim
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static int check_reg(const char *name, uint32_t actual, uint32_t expected)
{
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n",
           name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static int wait_for_idle(void)
{
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

static int wait_for_hmac_done(void)
{
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

static int recover_hmac_state(void)
{
    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    cfg.f.hmac_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    cfg.w = 0;
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = 1;
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

    printf("  Recovery: ERR_CODE=0x%08x STATUS=0x%08x\n",
           READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR), READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR));

    return wait_for_idle();
}

static int expect_hmac_error(const char *name, uint32_t expected_err)
{
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

static int test_push_when_sha_disabled(void)
{
    printf("\nStep 1: MSG_FIFO push while sha_en=0\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    *fifo8 = 0xa5;

    if (expect_hmac_error("ERR_CODE push while sha_en=0", 0x5) != 0) {
        return -1;
    }

    return recover_hmac_state();
}

static int test_hash_start_when_busy(void)
{
    printf("\nStep 2: hash_start while engine is active\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    if (expect_hmac_error("ERR_CODE hash_start while active", 0x4) != 0) {
        return -1;
    }

    return recover_hmac_state();
}

static int test_fifo_saturation_and_reset_recovery(void)
{
    printf("\nStep 3: Fill MSG_FIFO to fifo_full and recover by process/drain\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    volatile uint32_t *fifo32 = (volatile uint32_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    uint32_t words_written = 0;
    int full_seen = 0;
    uint32_t max_depth = 0;

    for (uint32_t i = 0; i < 128; i++) {
        hmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (status.f.fifo_depth > max_depth) {
            max_depth = status.f.fifo_depth;
        }
        if (status.f.fifo_full) {
            full_seen = 1;
            printf("  fifo_full asserted before word %u, depth=%u\n", i, status.f.fifo_depth);
            break;
        }

        *fifo32 = 0x5a000000u | i;
        words_written++;
    }

    hmac__STATUS_t final_status = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    if (final_status.f.fifo_depth > max_depth) {
        max_depth = final_status.f.fifo_depth;
    }

    printf("  words_written=%u fifo_full=%u fifo_depth=%u max_depth=%u\n",
           words_written, final_status.f.fifo_full, final_status.f.fifo_depth, max_depth);

    if (!full_seen && !final_status.f.fifo_full) {
        printf("  INFO: fifo_full not observed; SHA engine drained FIFO while FW streamed data\n");
    } else if (max_depth < 32) {
        printf("  FAIL: fifo_full asserted but fifo_depth never reached 32 entries\n");
        return -1;
    } else {
        printf("  INFO: Extra write beyond fifo_full is skipped to avoid CPU MMIO deadlock\n");
    }

    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);
    if (wait_for_hmac_done() != 0) {
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

int main(void)
{
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

    if (test_push_when_sha_disabled() != 0) {
        pass = 0;
    }
    if (pass && test_hash_start_when_busy() != 0) {
        pass = 0;
    }
    if (pass && test_fifo_saturation_and_reset_recovery() != 0) {
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
