/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*
 * TC_KMAC_010 - PREFIX Register Test (P1)
 *
 * Verifies PREFIX register write/readback for all 11 words.
 * Runs KMAC with standard prefix, then custom prefix, and
 * verifies the two digests are different.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        if (READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & 0x1) {
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1);
            return 0;
        }
    }
    printf("Timeout waiting for done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static const uint32_t test_key[4] = {
    0xAABBCCDD, 0x11223344, 0x55667788, 0x99AABBCC
};

static int run_kmac_with_prefix(const uint32_t *prefix, uint32_t *digest_out) {
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 1;
    cfg.f.mode = 0x3;   // cSHAKE = value 3 per hjson (sha3_mode_e::CShake = 2'b11); KMAC requires cSHAKE for PREFIX
    cfg.f.kstrength = 0x0;
    cfg.f.entropy_mode = 0x1;  /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    setup_entropy();

    cfg.f.entropy_ready = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    kmac__KEY_LEN_t kl = {.w = 0};
    kl.f.len = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, kl.w);

    for (int i = 0; i < 4; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE0_BASE_ADDR(0) + (i * 4), test_key[i]);
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE1_BASE_ADDR(0) + (i * 4), 0);
    }

    for (int i = 0; i < 11; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0) + (i * 4), prefix[i]);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574);

    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x00020001);

    cmd.f.cmd = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        uint32_t s0 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4));
        uint32_t s1 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + 0x100 + (i * 4));
        digest_out[i] = s0 ^ s1;
    }

    cmd.f.cmd = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return 0;
}

static int test_prefix(void) {
    int errors = 0;
    uint32_t val;

    printf("=== Step 1: PREFIX write/readback test ===\n");
    static const uint32_t test_vals[11] = {
        0x12345678, 0x9ABCDEF0, 0xA5A5A5A5, 0x5A5A5A5A,
        0xDEADBEEF, 0xCAFEBABE, 0x01020304, 0x05060708,
        0x090A0B0C, 0x0D0E0F10, 0x11121314
    };

    for (int i = 0; i < 11; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0) + (i * 4), test_vals[i]);

    for (int i = 0; i < 11; i++) {
        val = READ_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0) + (i * 4));
        if (val != test_vals[i]) {
            printf("FAIL: PREFIX_%d readback 0x%08x, expected 0x%08x\n",
                   i, val, test_vals[i]);
            errors++;
        }
    }
    printf("PREFIX write/readback: %s\n", errors == 0 ? "PASS" : "FAIL");

    printf("=== Step 2: Clear PREFIX to zeros ===\n");
    for (int i = 0; i < 11; i++)
        WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0) + (i * 4), 0);

    int clear_ok = 1;
    for (int i = 0; i < 11; i++) {
        val = READ_REG(OCH_SEP_TOP_KMAC_PREFIX_BASE_ADDR(0) + (i * 4));
        if (val != 0) { clear_ok = 0; errors++; }
    }
    printf("PREFIX clear: %s\n", clear_ok ? "PASS" : "FAIL");

    printf("=== Step 3: KMAC with standard prefix ===\n");
    static const uint32_t std_prefix[11] = {
        0x4D4B2001, 0x00004341, 0, 0, 0, 0, 0, 0, 0, 0, 0
    };
    uint32_t digest_std[8];
    if (run_kmac_with_prefix(std_prefix, digest_std) != 0) {
        printf("FAIL: standard prefix KMAC failed\n");
        return errors + 1;
    }
    printf("Digest (std prefix): ");
    for (int i = 0; i < 8; i++) printf("%08x ", digest_std[i]);
    printf("\n");

    printf("=== Step 4: KMAC with custom prefix ===\n");
    static const uint32_t cust_prefix[11] = {
        0x54534554, 0x00000001, 0, 0, 0, 0, 0, 0, 0, 0, 0
    };
    uint32_t digest_cust[8];
    if (run_kmac_with_prefix(cust_prefix, digest_cust) != 0) {
        printf("FAIL: custom prefix KMAC failed\n");
        return errors + 1;
    }
    printf("Digest (cust prefix): ");
    for (int i = 0; i < 8; i++) printf("%08x ", digest_cust[i]);
    printf("\n");

    printf("=== Step 5: Compare digests ===\n");
    int same = 1;
    for (int i = 0; i < 8; i++) {
        if (digest_std[i] != digest_cust[i]) { same = 0; break; }
    }
    if (same) {
        printf("FAIL: digests identical with different prefixes\n");
        errors++;
    } else {
        printf("PASS: digests differ as expected\n");
    }

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  TC_KMAC_010: PREFIX Register Test\n");
    printf("========================================\n\n");

    int result = test_prefix();

    if (result == 0) {
        printf("\n=== TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== TEST FAILED (errors=%d) ===\n", result);
        test_fail(1);
    }

    while (1) { __asm__("wfi"); }
}
