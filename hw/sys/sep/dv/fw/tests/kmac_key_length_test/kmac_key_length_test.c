/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_KMAC_009 - Key Length Test (P1)
 *
 * Runs KMAC-128 with Key128 (4-word key), saves digest.
 * Runs KMAC-128 with Key256 (8-word key), saves digest.
 * Verifies the two digests are different.
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
        if (s.f.SHA3_IDLE) return 0;
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
    for (int i = 0; i < 6; i++) WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static int run_kmac128(const uint32_t *key, int key_words, uint32_t key_len_val,
                       uint32_t *digest_out) {
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 1;
    cfg.f.MODE = 0x2;
    cfg.f.KSTRENGTH = 0x0;
    cfg.f.ENTROPY_MODE = 0x1; /* EDN mode = 0x1 (same as kmac_test which passes) */
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    setup_entropy();

    cfg.f.ENTROPY_READY = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    kmac__KEY_LEN_t kl = {.w = 0};
    kl.f.LEN = key_len_val;
    WRITE_REG(OCH_SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, kl.w);

    for (int i = 0; i < key_words; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE0_0_BASE_ADDR(i), key[i]);
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE1_0_BASE_ADDR(i), 0);
    }

    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_0_BASE_ADDR(0), 0x4D4B2001);
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_0_BASE_ADDR(0) + 4, 0x00004341);
    for (int i = 2; i < 11; i++) WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_0_BASE_ADDR(i), 0);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.CMD = 29;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR(0), 0x74736574);

    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR(0), 0x00020001);

    cmd.f.CMD = 46;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        uint32_t s0 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(i * 4));
        uint32_t s1 = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(0x100 + (i * 4)));
        digest_out[i] = s0 ^ s1;
    }

    cmd.f.CMD = 22;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return 0;
}

static int test_key_length(void) {
    int errors = 0;

    static const uint32_t key128[4] = {0x11111111, 0x22222222, 0x33333333, 0x44444444};
    static const uint32_t key256[8] = {0x11111111, 0x22222222, 0x33333333, 0x44444444,
                                       0x55555555, 0x66666666, 0x77777777, 0x88888888};

    uint32_t digest_128[8];
    uint32_t digest_256[8];

    printf("=== Run 1: KMAC-128 with Key128 (4 words) ===\n");
    if (run_kmac128(key128, 4, 0, digest_128) != 0) {
        printf("FAIL: Key128 run failed\n");
        return 1;
    }
    printf("Digest (Key128): ");
    for (int i = 0; i < 8; i++) printf("%08x ", digest_128[i]);
    printf("\n");

    printf("=== Run 2: KMAC-128 with Key256 (8 words) ===\n");
    if (run_kmac128(key256, 8, 2, digest_256) != 0) {
        printf("FAIL: Key256 run failed\n");
        return 1;
    }
    printf("Digest (Key256): ");
    for (int i = 0; i < 8; i++) printf("%08x ", digest_256[i]);
    printf("\n");

    printf("=== Comparing digests ===\n");
    int same = 1;
    for (int i = 0; i < 8; i++) {
        if (digest_128[i] != digest_256[i]) {
            same = 0;
            break;
        }
    }
    if (same) {
        printf("FAIL: digests are identical with different key lengths\n");
        errors++;
    } else {
        printf("PASS: digests differ as expected\n");
    }

    int nz_128 = 0, nz_256 = 0;
    for (int i = 0; i < 8; i++) {
        if (digest_128[i] != 0) nz_128 = 1;
        if (digest_256[i] != 0) nz_256 = 1;
    }
    if (!nz_128) {
        printf("FAIL: Key128 digest all zeros\n");
        errors++;
    }
    if (!nz_256) {
        printf("FAIL: Key256 digest all zeros\n");
        errors++;
    }

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  TC_KMAC_009: Key Length Test\n");
    printf("========================================\n\n");

    int result = test_key_length();

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
