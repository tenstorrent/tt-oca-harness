/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC Interrupt Generation and Masking Test
 *
 * Verifies INTR_TEST forcing, INTR_STATE reflection, W1C clearing,
 * INTR_ENABLE masking behavior, and real hmac_done interrupt generation.
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
        hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) {
            break;
        }
    }
    if (timeout <= 0) {
        printf("  Timeout waiting for HMAC completion\n");
        return -1;
    }
    return 0;
}

static void clear_all_interrupts(void) {
    hmac__INTR_STATE_t clear = {.w = 0};
    clear.f.hmac_done = 1;
    clear.f.fifo_empty = 1;
    clear.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
}

static void hmac_cleanup(void) {
    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
    clear_all_interrupts();
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC Interrupt Test\n");
    printf("========================================\n\n");

    int pass = 1;

    /* Step 1: Enable all three interrupts */
    printf("Step 1: Enable all interrupts\n");
    hmac__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.hmac_done = 1;
    intr_en.f.fifo_empty = 1;
    intr_en.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    uint32_t rb = READ_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("INTR_ENABLE all set",
                   rb & (HMAC__INTR_ENABLE__HMAC_DONE_bm | HMAC__INTR_ENABLE__FIFO_EMPTY_bm |
                         HMAC__INTR_ENABLE__HMAC_ERR_bm),
                   HMAC__INTR_ENABLE__HMAC_DONE_bm | HMAC__INTR_ENABLE__FIFO_EMPTY_bm |
                       HMAC__INTR_ENABLE__HMAC_ERR_bm))
        pass = 0;

    clear_all_interrupts();
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, 0);

    /* Step 2: INTR_TEST hmac_done, verify and W1C clear */
    printf("\nStep 2: INTR_TEST hmac_done\n");
    hmac__INTR_TEST_t test_reg = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, test_reg.w);

    hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (!check_reg("INTR_STATE.hmac_done after INTR_TEST", intr.f.hmac_done, 1)) pass = 0;

    hmac__INTR_STATE_t w1c = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, w1c.w);
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.hmac_done after W1C", intr.f.hmac_done, 0)) pass = 0;

    /*
     * Step 3: fifo_empty IntrT path via INTR_TEST (FAIL-ON).
     * Idle STATUS.fifo_empty=1 is a precondition. INTR_STATE.fifo_empty does not
     * mirror STATUS.fifo_empty at idle, so this step forces the bit through
     * INTR_TEST and asserts nothing about that reflection.
     */
    printf("\nStep 3: fifo_empty INTR_TEST (idle STATUS precondition)\n");
    clear_all_interrupts();
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, 0);
    hmac__STATUS_t sts = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    printf("  Idle STATUS.fifo_empty=%u INTR_STATE.fifo_empty=%u\n", sts.f.fifo_empty,
           intr.f.fifo_empty);
    if (!sts.f.fifo_empty) {
        printf("  FAIL: idle FIFO not empty\n");
        pass = 0;
    }
    test_reg.w = 0;
    test_reg.f.fifo_empty = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, test_reg.w);
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.fifo_empty after INTR_TEST", intr.f.fifo_empty, 1)) pass = 0;
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, 0);
    clear_all_interrupts();

    /* Step 4: INTR_TEST hmac_err, verify and W1C clear */
    printf("\nStep 4: INTR_TEST hmac_err\n");
    test_reg.w = 0;
    test_reg.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, test_reg.w);

    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.hmac_err after INTR_TEST", intr.f.hmac_err, 1)) pass = 0;

    w1c.w = 0;
    w1c.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, w1c.w);
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.hmac_err after W1C", intr.f.hmac_err, 0)) pass = 0;

    /* Step 5: Disable hmac_done enable, INTR_TEST should still set INTR_STATE */
    printf("\nStep 5: Masking test - disable hmac_done, INTR_TEST still sets state\n");
    intr_en.w = 0;
    intr_en.f.hmac_done = 0;
    intr_en.f.fifo_empty = 1;
    intr_en.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    test_reg.w = 0;
    test_reg.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, test_reg.w);

    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.hmac_done (enable=0, INTR_TEST)", intr.f.hmac_done, 1)) pass = 0;

    w1c.w = 0;
    w1c.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, w1c.w);

    /* Step 6: Trigger real hmac_done via SHA-256 empty message */
    printf("\nStep 6: Real hmac_done - SHA-256 empty message\n");
    intr_en.w = 0;
    intr_en.f.hmac_done = 1;
    intr_en.f.fifo_empty = 1;
    intr_en.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    clear_all_interrupts();
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, 0);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    hmac__CMD_t cmd_proc = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_proc.w);

    if (wait_hmac_done() != 0) {
        pass = 0;
    }

    /* Step 7: Verify INTR_STATE.hmac_done set by real completion */
    printf("\nStep 7: Verify real hmac_done in INTR_STATE\n");
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE.hmac_done (real)", intr.f.hmac_done, 1)) pass = 0;

    /* Step 8: Clear and cleanup */
    printf("\nStep 8: Cleanup\n");
    hmac_cleanup();
    printf("  Cleanup complete\n");

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC INTERRUPT TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC INTERRUPT TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
