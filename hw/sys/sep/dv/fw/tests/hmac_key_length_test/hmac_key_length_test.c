/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_HMAC_009 (P1) - Key length configuration test
 *
 * Steps:
 *   1) For key_length values 0x01(128b), 0x02(256b), 0x04(384b), 0x08(512b):
 *      write CFG.key_length, readback verify
 *   2) Write a test key and HMAC-hash "test" with key_length=128 and key_length=256
 *   3) Verify the two digests differ (different effective key length => different HMAC)
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
        hmac__none__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_INTR_STATE_BASE_ADDR)};
        hmac__none__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_STATUS_BASE_ADDR)};
        if (intr.f.HMAC_DONE || sts.f.HMAC_IDLE) break;
    }
    if (timeout <= 0) {
        printf("Timeout waiting for HMAC completion\n");
        return -1;
    }
    hmac__none__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_INTR_STATE_BASE_ADDR)};
    if (intr.f.HMAC_DONE) {
        WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_STATE_BASE_ADDR, intr.w);
    }
    return 0;
}

static int feed_msg(const uint8_t *data, uint32_t len) {
    volatile uint8_t *fifo8 =
        (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_NONE_MSG_FIFO_BASE_ADDR(0);
    for (uint32_t i = 0; i < len; i++) {
        int spins = 0;
        hmac__none__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_STATUS_BASE_ADDR)};
        while (s.f.FIFO_FULL) {
            if (spins++ > 10000) {
                printf("FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_STATUS_BASE_ADDR);
        }
        *fifo8 = data[i];
    }
    return 0;
}

static int hmac_hash_with_key_length(uint32_t klen_val, uint32_t digest_out[8]) {
    /* Write a fixed test key to KEY_0..KEY_7 */
    for (int i = 0; i < 8; i++) {
        WRITE_REG(OCH_SEP_TOP_HMAC_NONE_KEY_0_BASE_ADDR(i), 0xDEADBEEFu + i);
    }

    hmac__none__INTR_ENABLE_t intr_en = {.f.HMAC_DONE = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__none__CFG_t cfg = {.w = 0};
    cfg.f.HMAC_EN = 1;
    cfg.f.SHA_EN = 1;
    cfg.f.DIGEST_SIZE = 1; /* SHA2_256 */
    cfg.f.KEY_LENGTH = klen_val;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

    hmac__none__CMD_t cmd = {.f.HASH_START = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CMD_BASE_ADDR, cmd.w);

    const uint8_t msg[] = "test";
    if (feed_msg(msg, 4) != 0) return -1;

    hmac__none__CMD_t proc = {.f.HASH_PROCESS = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CMD_BASE_ADDR, proc.w);

    if (wait_for_done_or_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        digest_out[i] = READ_REG(OCH_SEP_TOP_HMAC_NONE_DIGEST_0_BASE_ADDR(i));
    }

    /* Cleanup */
    hmac__none__CFG_t cfg_off = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR)};
    cfg_off.f.SHA_EN = 0;
    cfg_off.f.HMAC_EN = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg_off.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_ENABLE_BASE_ADDR, 0);

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("=== TC_HMAC_009: Key length configuration test ===\n");
    int pass = 1;

    /* Part 1: Readback verify key_length field for multiple values */
    uint32_t klen_vals[] = {0x01, 0x02, 0x04, 0x08};
    const char *klen_names[] = {"128b", "256b", "384b", "512b"};

    for (int t = 0; t < 4; t++) {
        hmac__none__CFG_t cfg = {.w = 0};
        cfg.f.SHA_EN = 1;
        cfg.f.DIGEST_SIZE = 1;
        cfg.f.KEY_LENGTH = klen_vals[t];
        WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

        hmac__none__CFG_t rb = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR)};
        printf("key_length=%s: wrote=0x%02x readback=0x%02x %s\n", klen_names[t], klen_vals[t],
               rb.f.KEY_LENGTH, (rb.f.KEY_LENGTH == klen_vals[t]) ? "OK" : "MISMATCH");
        if (rb.f.KEY_LENGTH != klen_vals[t]) {
            pass = 0;
        }
    }

    /* Part 2: HMAC with key_length=128 vs key_length=256 must produce different digests */
    uint32_t digest_128[8];
    uint32_t digest_256[8];

    printf("HMAC with key_length=128b...\n");
    if (hmac_hash_with_key_length(0x01, digest_128) != 0) {
        printf("FAIL: HMAC with key_length=128 failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    printf("HMAC with key_length=256b...\n");
    if (hmac_hash_with_key_length(0x02, digest_256) != 0) {
        printf("FAIL: HMAC with key_length=256 failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    printf("Digest (128b key):");
    for (int i = 0; i < 8; i++) printf(" 0x%08x", digest_128[i]);
    printf("\n");

    printf("Digest (256b key):");
    for (int i = 0; i < 8; i++) printf(" 0x%08x", digest_256[i]);
    printf("\n");

    int differ = 0;
    for (int i = 0; i < 8; i++) {
        if (digest_128[i] != digest_256[i]) differ = 1;
    }
    if (!differ) {
        printf("FAIL: 128b and 256b key lengths produced identical digests\n");
        pass = 0;
    } else {
        printf("OK: Different key lengths produce different digests\n");
    }

    if (pass) {
        printf("=== TC_HMAC_009 PASSED ===\n");
        test_pass(0);
    } else {
        printf("FAIL: TC_HMAC_009 key length test\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
