/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC CFG Digest Size Test - TC_HMAC_003 (P0)
 *
 * Verifies CFG.digest_size field for all SHA variants and CFG field independence.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_hmac_cfg_digest_size_test STACK=sim
 *
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

int main(void) {
    sep_outbound_filter_init();

    printf("\n============================================\n");
    printf("HMAC CFG Digest Size Test (TC_HMAC_003)\n");
    printf("============================================\n\n");

    int pass = 1;
    hmac__none__CFG_t cfg;

    printf("Step 1: Verify CFG default\n");
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("CFG default", cfg.w, 0u)) pass = 0;

    printf("\nStep 2: Set digest_size=SHA-256 (0x1)\n");
    cfg.w = 0;
    cfg.f.DIGEST_SIZE = 0x1;
    cfg.f.SHA_EN = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("digest_size", cfg.f.DIGEST_SIZE, 0x1)) pass = 0;
    if (!check_reg("sha_en", cfg.f.SHA_EN, 1)) pass = 0;
    if (!check_reg("hmac_en", cfg.f.HMAC_EN, 0)) pass = 0;

    printf("\nStep 3: Set digest_size=SHA-384 (0x2)\n");
    cfg.w = 0;
    cfg.f.DIGEST_SIZE = 0x2;
    cfg.f.SHA_EN = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("digest_size", cfg.f.DIGEST_SIZE, 0x2)) pass = 0;

    printf("\nStep 4: Set digest_size=SHA-512 (0x4)\n");
    cfg.w = 0;
    cfg.f.DIGEST_SIZE = 0x4;
    cfg.f.SHA_EN = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("digest_size", cfg.f.DIGEST_SIZE, 0x4)) pass = 0;

    printf("\nStep 5: Verify hmac_en and sha_en independence\n");
    cfg.w = 0;
    cfg.f.HMAC_EN = 1;
    cfg.f.SHA_EN = 0;
    cfg.f.DIGEST_SIZE = 0x1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("hmac_en=1", cfg.f.HMAC_EN, 1)) pass = 0;
    if (!check_reg("sha_en=0", cfg.f.SHA_EN, 0)) pass = 0;

    cfg.f.HMAC_EN = 0;
    cfg.f.SHA_EN = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("hmac_en=0", cfg.f.HMAC_EN, 0)) pass = 0;
    if (!check_reg("sha_en=1", cfg.f.SHA_EN, 1)) pass = 0;

    printf("\nStep 6: Verify key_length field\n");
    cfg.w = 0;
    cfg.f.SHA_EN = 1;
    cfg.f.DIGEST_SIZE = 0x1;
    cfg.f.KEY_LENGTH = 0x02;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("key_length=0x02 (256b)", cfg.f.KEY_LENGTH, 0x02)) pass = 0;

    cfg.f.KEY_LENGTH = 0x08;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("key_length=0x08 (512b)", cfg.f.KEY_LENGTH, 0x08)) pass = 0;

    printf("\nStep 7: Verify swap fields\n");
    cfg.w = 0;
    cfg.f.SHA_EN = 1;
    cfg.f.DIGEST_SIZE = 0x1;
    cfg.f.ENDIAN_SWAP = 1;
    cfg.f.DIGEST_SWAP = 1;
    cfg.f.KEY_SWAP = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR);
    if (!check_reg("endian_swap=1", cfg.f.ENDIAN_SWAP, 1)) pass = 0;
    if (!check_reg("digest_swap=1", cfg.f.DIGEST_SWAP, 1)) pass = 0;
    if (!check_reg("key_swap=1", cfg.f.KEY_SWAP, 1)) pass = 0;

    /* Restore default */
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, 0u);

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
