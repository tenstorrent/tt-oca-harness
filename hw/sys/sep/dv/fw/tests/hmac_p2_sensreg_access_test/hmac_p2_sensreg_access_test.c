/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 Sensitive Register Access Test.
 *
 * Verifies security-sensitive register access behavior exposed by the current
 * HMAC register map:
 *   1) KEY registers are write-only: reads must not reveal written key values.
 *   2) DIGEST registers are HW-driven outside context restore: writes must not echo.
 *   3) CFG_REGWEN is not present in the current HMAC map; record this as N/A.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_hmac_p2_sensreg_access_test STACK=cgen,sim
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static int check_true(const char *name, int condition) {
    printf("  %s - %s\n", name, condition ? "PASS" : "FAIL");
    return condition;
}

static int test_key_read_protection(void) {
    printf("\nStep 1: KEY register read protection\n");

    int pass = 1;
    for (uint32_t i = 0; i < 8; i++) {
        uint32_t addr = OCH_SEP_TOP_HMAC_NONE_KEY_0_BASE_ADDR(i);
        uint32_t pattern = 0xa5a50000u | (i * 0x1111u) | i;

        WRITE_REG(addr, pattern);
        uint32_t rb = READ_REG(addr);
        printf("  KEY_%u wrote=0x%08x read=0x%08x\n", i, pattern, rb);

        if (rb == pattern) {
            printf("  FAIL: KEY_%u read exposed written key value\n", i);
            pass = 0;
        }
        if (rb != 0) {
            printf("  INFO: KEY_%u read returned non-zero protected value 0x%08x\n", i, rb);
        }
    }

    return pass ? 0 : -1;
}

static int test_digest_write_non_echo(void) {
    printf("\nStep 2: DIGEST write outside context restore must not echo\n");

    int pass = 1;
    for (uint32_t i = 0; i < 8; i++) {
        uint32_t addr = OCH_SEP_TOP_HMAC_NONE_DIGEST_0_BASE_ADDR(i);
        uint32_t before = READ_REG(addr);
        uint32_t pattern = 0x5a5a0000u | (i * 0x0101u) | i;

        WRITE_REG(addr, pattern);
        uint32_t after = READ_REG(addr);
        printf("  DIGEST_%u before=0x%08x wrote=0x%08x after=0x%08x\n", i, before, pattern, after);

        if (after == pattern) {
            printf("  FAIL: DIGEST_%u echoed SW write outside context restore\n", i);
            pass = 0;
        }
    }

    return pass ? 0 : -1;
}

static int test_cfg_regwen_absent(void) {
    printf("\nStep 3: CFG_REGWEN lock behavior\n");
    printf("  INFO: HMAC_CFG_REGWEN is not present in sep.h / sep_addr.h; step is N/A\n");

    hmac__none__CFG_t cfg = {.w = 0};
    cfg.f.SHA_EN = 1;
    cfg.f.HMAC_EN = 0;
    cfg.f.DIGEST_SIZE = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

    hmac__none__CFG_t rb = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR)};
    printf("  CFG write/readback without regwen: wrote=0x%08x read=0x%08x\n", cfg.w, rb.w);

    cfg.f.SHA_EN = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

    return check_true("CFG remains writable because no regwen register exists", rb.w == cfg.w);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC P2 Sensitive Register Access Test\n");
    printf("========================================\n");

    int pass = 1;

    if (test_key_read_protection() != 0) {
        pass = 0;
    }
    if (pass && test_digest_write_non_echo() != 0) {
        pass = 0;
    }
    if (pass && test_cfg_regwen_absent() != 0) {
        pass = 0;
    }

    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_WIPE_SECRET_BASE_ADDR, 0xffffffffu);
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_ENABLE_BASE_ADDR, 0);

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC P2 SENSITIVE REGISTER ACCESS TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC P2 SENSITIVE REGISTER ACCESS TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
