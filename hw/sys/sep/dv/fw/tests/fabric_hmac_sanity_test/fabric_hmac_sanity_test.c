/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Fabric HMAC Sanity Test
 *
 * Lightweight firmware check for the SEP fabric path to HMAC registers.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static int check_bit(const char *name, uint32_t value) {
    printf("%s: %u - %s\n", name, value, value ? "PASS" : "FAIL");
    return value ? 1 : 0;
}

int main(void) {
    int pass = 1;

    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("Fabric HMAC Sanity Test\n");
    printf("========================================\n\n");

    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    uint32_t err_code = READ_REG(SEP_TOP_HMAC_ERR_CODE_BASE_ADDR);

    printf("HMAC_CFG    = 0x%08x\n", cfg.w);
    printf("HMAC_STATUS = 0x%08x idle=%u empty=%u full=%u depth=%u\n", status.w, status.f.hmac_idle,
           status.f.fifo_empty, status.f.fifo_full, status.f.fifo_depth);
    printf("HMAC_ERR_CODE = 0x%08x\n", err_code);

    if (!check_bit("HMAC idle", status.f.hmac_idle)) {
        pass = 0;
    }
    if (!check_bit("HMAC FIFO empty", status.f.fifo_empty)) {
        pass = 0;
    }
    if (err_code != 0u) {
        printf("Unexpected HMAC_ERR_CODE default\n");
        pass = 0;
    }

    hmac__INTR_TEST_t intr_test = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, intr_test.w);

    hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (!check_bit("HMAC INTR_TEST hmac_done", intr.f.hmac_done)) {
        pass = 0;
    }

    hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);

    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (intr.f.hmac_done != 0) {
        printf("HMAC hmac_done interrupt did not clear\n");
        pass = 0;
    }

    if (pass) {
        printf("=== FABRIC HMAC SANITY TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== FABRIC HMAC SANITY TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
