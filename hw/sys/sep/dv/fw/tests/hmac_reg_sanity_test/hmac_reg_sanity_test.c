/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC Register Sanity Test
 *
 * Verifies register default readback and basic RW access for HMAC.
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

static int check_rw(const char *name, uint32_t addr, uint32_t val) {
    WRITE_REG(addr, val);
    uint32_t rb = READ_REG(addr);
    return check_reg(name, rb, val);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC Register Sanity Test\n");
    printf("========================================\n\n");

    int pass = 1;

    printf("Step 1: Check defaults\n");
    if (!check_reg("STATUS", READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR), 0x3)) pass = 0;
    if (!check_reg("CFG", READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR), 0u)) pass = 0;
    if (!check_reg("ERR_CODE", READ_REG(SEP_TOP_HMAC_ERR_CODE_BASE_ADDR), 0x0)) pass = 0;
    if (!check_reg("INTR_ENABLE", READ_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR), 0x0)) pass = 0;
    if (!check_reg("INTR_STATE", READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR), 0x0)) pass = 0;

    printf("\nStep 2: INTR_ENABLE RW\n");
    if (!check_rw("INTR_ENABLE=0x7", SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0x7)) pass = 0;
    if (!check_rw("INTR_ENABLE=0x0", SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0x0)) pass = 0;

    printf("\nStep 3: INTR_TEST -> INTR_STATE\n");
    hmac__INTR_TEST_t intr_test = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, intr_test.w);
    hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (!check_reg("INTR_STATE.hmac_done after INTR_TEST", intr.f.hmac_done, 1)) pass = 0;

    printf("\nStep 4: W1C clear INTR_STATE\n");
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, intr.w);
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (!check_reg("INTR_STATE after W1C", intr.w, 0x0)) pass = 0;

    printf("\nStep 5: MSG_LENGTH RW\n");
    if (!check_rw("MSG_LENGTH_LOWER=0x12345678", SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR,
                  0x12345678))
        pass = 0;
    if (!check_rw("MSG_LENGTH_UPPER=0x9ABCDEF0", SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR,
                  0x9ABCDEF0))
        pass = 0;
    WRITE_REG(SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR, 0);

    printf("\nStep 6: DIGEST_0 default read (HW-driven, not SW RW)\n");
    /* The digest is hardware-driven; software writes only restore context before
     * hash_continue, so the test checks the reset value only. */
    if (!check_reg("DIGEST_0 default=0", READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(0)), 0x0)) pass = 0;

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC REG SANITY TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC REG SANITY TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
