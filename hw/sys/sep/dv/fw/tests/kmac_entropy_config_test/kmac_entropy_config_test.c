/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Entropy Configuration Test
 *
 * Verifies KMAC entropy period register, entropy seed provisioning,
 * and entropy_ready flow. Runs KMAC-128 (keyblock) so HASH_CNT increments,
 * then reads ENTROPY_REFRESH_HASH_CNT.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
/* Fixed KMAC-128(zero-key, "test", 256) digest from sep_kmac128_sw_smoke. */
static const uint32_t expected_smoke_digest[8] = {
    0xddfe0cb1u, 0x2d03e2e8u, 0x599a8018u, 0xb3142692u,
    0x342fa6a8u, 0xcb802413u, 0x00c7694fu, 0x92934aa6u,
};

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for idle\n");
    return -1;
}

static int test_entropy_config(void) {
    int errors = 0;
    uint32_t val;

    printf("=== Step 1: Read ENTROPY_PERIOD default ===\n");
    val = READ_REG(SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR);
    printf("ENTROPY_PERIOD default = 0x%08x\n", val);
    if (val != 0x00000000) {
        printf("FAIL: expected default 0x00000000\n");
        errors++;
    }

    printf("=== Step 2: Write ENTROPY_PERIOD 0x03FF0100 ===\n");
    WRITE_REG(SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR, 0x03FF0100);
    val = READ_REG(SEP_TOP_KMAC_ENTROPY_PERIOD_BASE_ADDR);
    printf("ENTROPY_PERIOD readback = 0x%08x\n", val);
    kmac__ENTROPY_PERIOD_t ep = {.w = val};
    printf("  prescaler=%u wait_timer=%u\n", ep.f.prescaler, ep.f.wait_timer);
    if (val != 0x03FF0100) {
        printf("FAIL: readback mismatch\n");
        errors++;
    }

    printf("=== Step 3/4/5/6: KMAC-128 SW-entropy hash (keyblock increments HASH_CNT) ===\n");
    if (wait_for_idle() != 0) return -1;

    /* HASH_CNT only increments on KMAC keyblock completion, not bare SHA3. */
    kmac__CMD_t clr = {.w = 0};
    clr.f.hash_cnt_clr = 1;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, clr.w);

    kmac__ENTROPY_REFRESH_THRESHOLD_SHADOWED_t thr = {.w = 0};
    thr.f.threshold = 0; /* disable auto-clear on threshold */
    WRITE_REG(SEP_TOP_KMAC_ENTROPY_REFRESH_THRESHOLD_SHADOWED_BASE_ADDR, thr.w);
    WRITE_REG(SEP_TOP_KMAC_ENTROPY_REFRESH_THRESHOLD_SHADOWED_BASE_ADDR, thr.w);

    uint32_t digest[8];
    int smoke = sep_kmac128_sw_smoke(digest);
    if (smoke != 0) {
        printf("FAIL: sep_kmac128_sw_smoke returned %d\n", smoke);
        errors++;
    } else {
        printf("Digest: ");
        for (int i = 0; i < 8; i++) printf("%08x ", digest[i]);
        printf("\n");
        {
            int mismatch = 0;
            for (int i = 0; i < 8; i++)
                if (digest[i] != expected_smoke_digest[i]) mismatch = 1;
            if (mismatch) {
                printf("FAIL: smoke digest != expected vector\n");
                errors++;
            } else {
                printf("PASS: smoke digest matches expected vector\n");
            }
        }
    }

    printf("=== Step 7: Read ENTROPY_REFRESH_HASH_CNT (expect == 1 after KMAC) ===\n");
    kmac__ENTROPY_REFRESH_HASH_CNT_t hc = {
        .w = READ_REG(SEP_TOP_KMAC_ENTROPY_REFRESH_HASH_CNT_BASE_ADDR)};
    printf("ENTROPY_REFRESH_HASH_CNT = %u\n", hc.f.hash_cnt);
    if (hc.f.hash_cnt == 1) {
        printf("PASS: hash_cnt==1 after one KMAC keyblock\n");
    } else {
        printf("FAIL: hash_cnt=%u expected 1 after one KMAC keyblock\n", hc.f.hash_cnt);
        errors++;
    }

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  Entropy Config Test\n");
    printf("========================================\n\n");

    int result = test_entropy_config();

    if (result == 0) {
        printf("\n=== TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== TEST FAILED (errors=%d) ===\n", result);
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
