/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC P2 Shadow Protection Test.
 *
 * Verifies CFG_SHADOWED double-write protection:
 *   1) Matching double-write commits a valid configuration.
 *   2) Mismatched double-write does not commit the second value.
 *   3) Recoverable shadow update alert status is observed when exposed.
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
#include "test_completion.h"

static void write_cfg_shadowed_twice(uint32_t val) {
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, val);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, val);
}

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (status.f.sha3_idle) {
            return 0;
        }
    }

    printf("  Timeout waiting for KMAC idle\n");
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("KMAC P2 Shadow Protection Test\n");
    printf("========================================\n");

    int pass = 1;
    if (wait_for_idle() != 0) {
        pass = 0;
    }

    kmac__CFG_REGWEN_t regwen = {.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR)};
    printf("  CFG_REGWEN.en=%u\n", regwen.f.en);
    if (regwen.f.en != 1) {
        printf("  FAIL: CFG_SHADOWED is not writable at idle\n");
        pass = 0;
    }

    printf("\nStep 1: Valid matching shadowed write\n");
    kmac__CFG_SHADOWED_t valid = {.w = 0};
    valid.f.kmac_en = 0;
    valid.f.mode = SEP_KMAC_MODE_SHA3;
    valid.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    valid.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    write_cfg_shadowed_twice(valid.w);

    uint32_t committed = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    printf("  wrote=0x%08x read=0x%08x\n", valid.w, committed);
    if (committed != valid.w) {
        printf("  FAIL: matching shadowed write did not commit\n");
        pass = 0;
    }

    printf("\nStep 2: Mismatched shadowed write should be rejected\n");
    kmac__CFG_SHADOWED_t first = valid;
    first.f.mode = SEP_KMAC_MODE_RESERVED;
    first.f.kstrength = SEP_KMAC_KSTRENGTH_L256;

    kmac__CFG_SHADOWED_t second = valid;
    second.f.mode = SEP_KMAC_MODE_SHAKE;
    second.f.kstrength = SEP_KMAC_KSTRENGTH_L128;

    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, first.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, second.w);

    uint32_t after_bad = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    kmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    printf("  first=0x%08x second=0x%08x after=0x%08x\n", first.w, second.w, after_bad);
    printf("  STATUS=0x%08x alert_recov_ctrl_update_err=%u alert_fatal_fault=%u\n", status.w,
           status.f.ALERT_RECOV_CTRL_UPDATE_ERR, status.f.ALERT_FATAL_FAULT);

    if (after_bad == second.w) {
        printf("  FAIL: mismatched second shadow write committed\n");
        pass = 0;
    }
    if (after_bad != valid.w) {
        printf("  FAIL: residual CFG after mismatch is 0x%08x (expected prior valid 0x%08x)\n",
               after_bad, valid.w);
        pass = 0;
    } else {
        printf("  PASS: residual CFG remains prior valid value after mismatch\n");
    }
    if (status.f.ALERT_RECOV_CTRL_UPDATE_ERR) {
        printf("  PASS: recoverable shadow update alert observed\n");
    } else {
        printf("  FAIL: ALERT_RECOV_CTRL_UPDATE_ERR not set after intentional shadow mismatch\n");
        pass = 0;
    }

    printf("\nStep 3: Restore valid configuration after mismatch\n");
    write_cfg_shadowed_twice(valid.w);
    uint32_t restored = READ_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR);
    printf("  restored read=0x%08x\n", restored);
    if (restored != valid.w) {
        printf("  FAIL: CFG_SHADOWED did not accept valid write after mismatch\n");
        pass = 0;
    }

    WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm |
                                                         KMAC__INTR_STATE__FIFO_EMPTY_bm |
                                                         KMAC__INTR_STATE__KMAC_ERR_bm);

    printf("\n========================================\n");
    if (pass) {
        printf("=== KMAC P2 SHADOW PROTECTION TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== KMAC P2 SHADOW PROTECTION TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
