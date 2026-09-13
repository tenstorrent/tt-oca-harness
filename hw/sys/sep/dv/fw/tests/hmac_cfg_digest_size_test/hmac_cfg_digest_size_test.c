/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC CFG Digest Size Test
 *
 * Verifies CFG.digest_size field for all SHA variants and CFG field independence.
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

int main(void) {
    sep_outbound_filter_init();

    printf("\n============================================\n");
    printf("HMAC CFG Digest Size Test\n");
    printf("============================================\n\n");

    int pass = 1;
    hmac__CFG_t cfg;

    printf("Step 1: Verify CFG default\n");
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("CFG default", cfg.w, HMAC__CFG_reset)) pass = 0;

    printf("\nStep 2: Set digest_size=SHA-256 (0x1)\n");
    cfg.w = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    cfg.f.sha_en = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("digest_size", cfg.f.digest_size, SEP_HMAC_DIGEST_SIZE_SHA2_256)) pass = 0;
    if (!check_reg("sha_en", cfg.f.sha_en, 1)) pass = 0;
    if (!check_reg("hmac_en", cfg.f.hmac_en, 0)) pass = 0;

    printf("\nStep 3: Set digest_size=SHA-384 (0x2)\n");
    cfg.w = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_384;
    cfg.f.sha_en = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("digest_size", cfg.f.digest_size, SEP_HMAC_DIGEST_SIZE_SHA2_384)) pass = 0;

    printf("\nStep 4: Set digest_size=SHA-512 (0x4)\n");
    cfg.w = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_512;
    cfg.f.sha_en = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("digest_size", cfg.f.digest_size, SEP_HMAC_DIGEST_SIZE_SHA2_512)) pass = 0;

    printf("\nStep 5: Verify hmac_en and sha_en independence\n");
    cfg.w = 0;
    cfg.f.hmac_en = 1;
    cfg.f.sha_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("hmac_en=1", cfg.f.hmac_en, 1)) pass = 0;
    if (!check_reg("sha_en=0", cfg.f.sha_en, 0)) pass = 0;

    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("hmac_en=0", cfg.f.hmac_en, 0)) pass = 0;
    if (!check_reg("sha_en=1", cfg.f.sha_en, 1)) pass = 0;

    printf("\nStep 6: Verify key_length field\n");
    cfg.w = 0;
    cfg.f.sha_en = 1;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    cfg.f.key_length = SEP_HMAC_KEY_LENGTH_256;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("key_length=256b", cfg.f.key_length, SEP_HMAC_KEY_LENGTH_256)) pass = 0;

    cfg.f.key_length = SEP_HMAC_KEY_LENGTH_512;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("key_length=512b", cfg.f.key_length, SEP_HMAC_KEY_LENGTH_512)) pass = 0;

    printf("\nStep 7: Verify swap fields\n");
    cfg.w = 0;
    cfg.f.sha_en = 1;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    cfg.f.endian_swap = 1;
    cfg.f.digest_swap = 1;
    cfg.f.key_swap = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    if (!check_reg("endian_swap=1", cfg.f.endian_swap, 1)) pass = 0;
    if (!check_reg("digest_swap=1", cfg.f.digest_swap, 1)) pass = 0;
    if (!check_reg("key_swap=1", cfg.f.key_swap, 1)) pass = 0;

    /* Restore default */
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, 0u);

    printf("\n============================================\n");
    if (pass) {
        printf("=== HMAC CFG DIGEST SIZE TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC CFG DIGEST SIZE TEST FAILED ===\n");
        test_fail(0);
    }
    printf("============================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
