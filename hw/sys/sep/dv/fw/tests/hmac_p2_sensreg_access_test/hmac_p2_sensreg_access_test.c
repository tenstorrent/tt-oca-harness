/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 Sensitive Register Access Test.
 *
 * Verifies security-sensitive register access behavior exposed by the HMAC
 * register map:
 *   0) Positive control: CFG MMIO write/readback proves the HMAC window is live.
 *   1) KEY registers are write-only: reads must not reveal written key values.
 *   2) DIGEST registers are SW-writable while IDLE (context restore).
 *   3) CFG_REGWEN is not in the HMAC register map; this step reports N/A.
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"
#include "test_completion.h"
static int check_true(const char *name, int condition) {
    printf("  %s - %s\n", name, condition ? "PASS" : "FAIL");
    return condition ? 0 : -1;
}

static int test_mmio_positive_control(void) {
    printf("\nStep 0: Positive control - CFG MMIO write/readback\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CFG_t rb = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    printf("  CFG wrote=0x%08x read=0x%08x\n", cfg.w, rb.w);

    int ok = 1;
    if (rb.f.sha_en != 1 || rb.f.digest_size != SEP_HMAC_DIGEST_SIZE_SHA2_256) {
        printf("  FAIL: CFG readback does not match write (MMIO dead?)\n");
        ok = 0;
    }

    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    return ok ? 0 : -1;
}

static int test_key_read_protection(void) {
    printf("\nStep 1: KEY register read protection\n");

    int pass = 1;
    for (uint32_t i = 0; i < 8; i++) {
        uint32_t addr = OCH_SEP_TOP_HMAC_KEY_BASE_ADDR(i);
        uint32_t pattern = 0xa5a50000u | (i * 0x1111u) | i;

        WRITE_REG(addr, pattern);
        uint32_t rb = READ_REG(addr);
        printf("  KEY_%u wrote=0x%08x read=0x%08x\n", i, pattern, rb);

        /* Exact expectation: write-only KEY reads as 0 (OT HMAC KEY). */
        if (rb != 0) {
            printf("  FAIL: KEY_%u read returned 0x%08x (expected 0)\n", i, rb);
            pass = 0;
        }
        if (rb == pattern) {
            printf("  FAIL: KEY_%u read exposed written key value\n", i);
            pass = 0;
        }
    }

    return pass ? 0 : -1;
}

static int test_digest_write_context_restore(void) {
    /*
     * OT hmac.hjson: when IDLE, DIGEST is SW-writable for context restore.
     * Prove write/readback works, then wipe so later tests start clean.
     */
    printf("\nStep 2: DIGEST write/readback while IDLE (context restore path)\n");

    int pass = 1;
    for (uint32_t i = 0; i < 8; i++) {
        uint32_t addr = OCH_SEP_TOP_HMAC_DIGEST_BASE_ADDR(i);
        uint32_t pattern = 0x5a5a0000u | (i * 0x0101u) | i;

        WRITE_REG(addr, pattern);
        uint32_t after = READ_REG(addr);
        printf("  DIGEST_%u wrote=0x%08x after=0x%08x\n", i, pattern, after);

        if (after != pattern) {
            printf("  FAIL: DIGEST_%u did not accept IDLE context-restore write\n", i);
            pass = 0;
        }
        WRITE_REG(addr, 0u);
    }

    return pass ? 0 : -1;
}

static int test_cfg_regwen_absent(void) {
    printf("\nStep 3: CFG_REGWEN lock behavior\n");
    printf("  INFO: HMAC_CFG_REGWEN is not present in sep.h / sep_addr.h; step is N/A\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CFG_t rb = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    printf("  CFG write/readback without regwen: wrote=0x%08x read=0x%08x\n", cfg.w, rb.w);

    /* Compare programmed fields only — key_length may retain reset Key_None. */
    int cmp_ok = (rb.f.sha_en == 1 && rb.f.hmac_en == 0 &&
                  rb.f.digest_size == SEP_HMAC_DIGEST_SIZE_SHA2_256);

    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    return check_true("CFG remains writable because no regwen register exists", cmp_ok);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC P2 Sensitive Register Access Test\n");
    printf("========================================\n");

    int pass = 1;

    if (test_mmio_positive_control() != 0) {
        pass = 0;
    }
    if (pass && test_key_read_protection() != 0) {
        pass = 0;
    }
    if (pass && test_digest_write_context_restore() != 0) {
        pass = 0;
    }
    if (pass && test_cfg_regwen_absent() != 0) {
        pass = 0;
    }

    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xffffffffu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

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
