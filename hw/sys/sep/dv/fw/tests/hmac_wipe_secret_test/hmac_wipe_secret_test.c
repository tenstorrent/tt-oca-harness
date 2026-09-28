/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * WIPE_SECRET test
 *
 * Steps:
 * 1) Hash "abc" with SHA-256, save digest
 * 2) Write WIPE_SECRET with 0xFFFFFFFF
 * 3) Read DIGEST_0..7 again, verify at least some words changed
 * 4) Verify STATUS returns idle
 * 5) Start new hash of "abc", verify correct digest is produced again
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000FFu) << 24) | ((x & 0x0000FF00u) << 8) | ((x & 0x00FF0000u) >> 8) |
           ((x & 0xFF000000u) >> 24);
}

static int wait_for_done_or_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) break;
    }
    if (timeout <= 0) {
        printf("Timeout waiting for HMAC completion\n");
        return -1;
    }
    hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.hmac_done) {
        WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, intr.w);
    }
    return 0;
}

static int feed_msg(const uint8_t *data, uint32_t len) {
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    for (uint32_t i = 0; i < len; i++) {
        int spins = 0;
        hmac__STATUS_t s = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        while (s.f.fifo_full) {
            if (spins++ > 10000) {
                printf("FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo8 = data[i];
    }
    return 0;
}

static void to_hex(const uint8_t *in, char *out, int len) {
    static const char *hex = "0123456789abcdef";
    for (int i = 0; i < len; i++) {
        out[2 * i + 0] = hex[(in[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[(in[i] >> 0) & 0xF];
    }
    out[2 * len] = '\0';
}

static int sha256_abc(uint32_t digest_words[8]) {
    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 1;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    const uint8_t abc[] = "abc";
    if (feed_msg(abc, 3) != 0) return -1;

    hmac__CMD_t proc = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, proc.w);

    if (wait_for_done_or_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        digest_words[i] = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
    }

    hmac__CFG_t cfg_off = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg_off.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg_off.w);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("=== WIPE_SECRET test ===\n");
    int pass = 1;

    /* Step 1: Hash "abc", save digest */
    uint32_t digest1[8];
    if (sha256_abc(digest1) != 0) {
        printf("FAIL: First SHA-256(abc) failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }
    printf("First digest words:");
    for (int i = 0; i < 8; i++) printf(" 0x%08x", digest1[i]);
    printf("\n");

    /* Step 2: WIPE_SECRET */
    printf("Writing WIPE_SECRET...\n");
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);

    /* Step 3: Each DIGEST word must equal the wipe pattern (OT WIPE_SECRET). */
    const uint32_t wipe_pattern = 0xFFFFFFFFu;
    uint32_t digest_wiped[8];
    for (int i = 0; i < 8; i++) {
        digest_wiped[i] = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
    }
    printf("Post-wipe digest words:");
    for (int i = 0; i < 8; i++) printf(" 0x%08x", digest_wiped[i]);
    printf("\n");

    for (int i = 0; i < 8; i++) {
        if (digest_wiped[i] != wipe_pattern) {
            printf("FAIL: DIGEST_%d=0x%08x after wipe, expected 0x%08x\n", i, digest_wiped[i],
                   wipe_pattern);
            pass = 0;
        }
    }

    /* Step 4: Verify STATUS returns idle */
    hmac__STATUS_t sts = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    printf("STATUS after wipe: idle=%u\n", sts.f.hmac_idle);
    if (!sts.f.hmac_idle) {
        printf("FAIL: HMAC not idle after WIPE_SECRET\n");
        pass = 0;
    }

    /* Step 5: Hash "abc" again, verify correct digest */
    uint32_t digest2[8];
    if (sha256_abc(digest2) != 0) {
        printf("FAIL: Second SHA-256(abc) failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    uint8_t d2_bytes[32];
    for (int i = 0; i < 8; i++) {
        ((uint32_t *)d2_bytes)[i] = bswap32(digest2[i]);
    }
    char got[65];
    to_hex(d2_bytes, got, 32);
    const char *abc_hex = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    printf("Re-hash digest: %s\n", got);
    printf("Expected: %s\n", abc_hex);
    if (strcmp(got, abc_hex) != 0) {
        printf("FAIL: Re-hash after wipe produced wrong digest\n");
        pass = 0;
    }

    if (pass) {
        printf("=== PASSED ===\n");
        test_pass(0);
    } else {
        printf("FAIL: WIPE_SECRET test\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
