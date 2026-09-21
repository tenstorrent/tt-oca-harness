/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Key Length Test
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
#include "sep_kmac.h"

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        if (READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & KMAC__INTR_STATE__KMAC_DONE_bm) {
            WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
            return 0;
        }
    }
    printf("Timeout waiting for done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++) WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static int run_kmac128(const uint32_t *key, int key_words, uint32_t key_len_val,
                       uint32_t *digest_out) {
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 1;
    cfg.f.mode = SEP_KMAC_MODE_CSHAKE; /* kmac_en=1 requires cSHAKE */
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L128;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    setup_entropy();

    kmac__KEY_LEN_t kl = {.w = 0};
    kl.f.len = key_len_val;
    WRITE_REG(SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, kl.w);

    /* Clear full key window so unused KEY_LEN lanes cannot leak prior runs. */
    for (int i = 0; i < 16; i++) {
        WRITE_REG(SEP_TOP_KMAC_KEY_SHARE0_BASE_ADDR(i), 0);
        WRITE_REG(SEP_TOP_KMAC_KEY_SHARE1_BASE_ADDR(i), 0);
    }
    for (int i = 0; i < key_words; i++) {
        WRITE_REG(SEP_TOP_KMAC_KEY_SHARE0_BASE_ADDR(i), key[i]);
        WRITE_REG(SEP_TOP_KMAC_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    /* encode_string("KMAC") || encode_string("") — PREFIX_1 must include left_encode(0)=0x01||0x00
     */
    WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x4D4B2001u);
    WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(1), 0x00014341u);
    for (int i = 2; i < 11; i++) WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(i), 0);

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    WRITE_REG(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574);

    /* right_encode(256) is exactly 3 bytes: 0x01 0x00 0x02 */
    {
        volatile uint8_t *fifo8 =
            (volatile uint8_t *)(uintptr_t)SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR;
        *fifo8 = 0x01u;
        *fifo8 = 0x00u;
        *fifo8 = 0x02u;
    }

    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        uint32_t s0 = READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4)));
        uint32_t s1 =
            READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + (i * 4)));
        digest_out[i] = s0 ^ s1;
    }

    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

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

    /* Independent KMAC-128 KATs (Crypto.Hash.KMAC128, LE key words, msg="test"). */
    static const uint32_t expected_128[8] = {0xaba341deu, 0x9753953fu, 0x926f1148u, 0x60be11a5u,
                                             0x8193af83u, 0xd8d90ea8u, 0x1aa1a0aau, 0xcd5d087du};
    static const uint32_t expected_256[8] = {0xcceed92cu, 0xf9a19c94u, 0x1d659f0fu, 0x70608141u,
                                             0x0beb45b8u, 0xb1e224e9u, 0x26791f52u, 0x209b1d2fu};

    printf("=== Comparing digests to independent KMAC-128 vectors ===\n");
    for (int i = 0; i < 8; i++) {
        if (digest_128[i] != expected_128[i]) {
            printf("FAIL: Key128 DIGEST_%d=0x%08x expected=0x%08x\n", i, digest_128[i],
                   expected_128[i]);
            errors++;
        }
        if (digest_256[i] != expected_256[i]) {
            printf("FAIL: Key256 DIGEST_%d=0x%08x expected=0x%08x\n", i, digest_256[i],
                   expected_256[i]);
            errors++;
        }
    }

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

    return errors;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("  Key Length Test\n");
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
