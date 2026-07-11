/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_HMAC_007 (P1) - HMAC-SHA256 with software key
 *
 * Uses RFC 4231 test case 2:
 *   Key  = "Jefe" (4 bytes, zero-padded to 256 bits)
 *   Data = "what do ya want for nothing?"
 *   Expected HMAC-SHA256 =
 *     5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843
 *
 * Steps:
 *   1) Write 256-bit key to KEY_0..KEY_7 (pad "Jefe" with zeros)
 *   2) Configure: hmac_en=1, sha_en=1, digest_size=SHA-256, key_length=0x02 (256b)
 *   3) hash_start, feed message, hash_process
 *   4) Wait done, read digest, bswap32, compare
 *   5) WIPE_SECRET cleanup
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000FFu) << 24) | ((x & 0x0000FF00u) << 8) | ((x & 0x00FF0000u) >> 8) |
           ((x & 0xFF000000u) >> 24);
}

static int wait_for_done_or_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.HMAC_DONE || sts.f.HMAC_IDLE) break;
    }
    if (timeout <= 0) {
        printf("Timeout waiting for HMAC completion\n");
        return -1;
    }
    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.HMAC_DONE) {
        WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, intr.w);
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

static int feed_msg(const uint8_t *data, uint32_t len) {
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR(0);
    for (uint32_t i = 0; i < len; i++) {
        int spins = 0;
        hmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        while (s.f.FIFO_FULL) {
            if (spins++ > 10000) {
                printf("FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo8 = data[i];
    }
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("=== TC_HMAC_007: HMAC-SHA256 with software key ===\n");

    /* RFC 4231 test case 2 key: "Jefe" = 0x4a656665 */
    uint32_t key[8] = {0};
    key[0] = 0x4a656665;

    /* Write key to KEY_0..KEY_7 */
    for (int i = 0; i < 8; i++) {
        WRITE_REG(OCH_SEP_TOP_HMAC_KEY_0_BASE_ADDR(i), key[i]);
    }

    /* Enable hmac_done interrupt */
    hmac__INTR_ENABLE_t intr_en = {.f.HMAC_DONE = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    /* Configure: HMAC mode, SHA-256, key_length=256b (0x02) */
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.HMAC_EN = 1;
    cfg.f.SHA_EN = 1;
    cfg.f.ENDIAN_SWAP = 0;
    cfg.f.DIGEST_SWAP = 0;
    cfg.f.DIGEST_SIZE = 1;   /* SHA2_256 */
    cfg.f.KEY_LENGTH = 0x02; /* 256-bit key */
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    /* Start hash */
    hmac__CMD_t cmd = {.f.HASH_START = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    /* Feed message: "what do ya want for nothing?" */
    const uint8_t msg[] = "what do ya want for nothing?";
    uint32_t msg_len = 28;
    if (feed_msg(msg, msg_len) != 0) {
        printf("FAIL: FIFO feed error\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    /* Process */
    hmac__CMD_t proc = {.f.HASH_PROCESS = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, proc.w);

    if (wait_for_done_or_idle() != 0) {
        printf("FAIL: Timeout\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    /* Read digest and byte-swap */
    uint8_t digest[32];
    for (int i = 0; i < 8; i++) {
        uint32_t raw = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_0_BASE_ADDR(i));
        ((uint32_t *)digest)[i] = bswap32(raw);
    }

    char got[65];
    to_hex(digest, got, 32);
    const char *expected = "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843";

    printf("Digest:   %s\n", got);
    printf("Expected: %s\n", expected);

    /* Cleanup: disable and wipe */
    hmac__CFG_t cfg_off = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg_off.f.SHA_EN = 0;
    cfg_off.f.HMAC_EN = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg_off.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

    if (strcmp(got, expected) == 0) {
        printf("=== TC_HMAC_007 PASSED ===\n");
        test_pass(0);
    } else {
        printf("FAIL: Digest mismatch\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
