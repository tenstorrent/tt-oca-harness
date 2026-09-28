/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Hash stop/continue for multi-part hashing
 *
 * Steps:
 * 1) Single-pass: hash "Hello World!" in one shot, save digest
 * 2) Multi-part: hash_start, feed "Hello ", hash_stop, verify idle,
 * hash_continue, feed "World!", hash_process, read digest
 * 3) Compare: both digests must match
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

static void read_digest(uint8_t digest[32]) {
    for (int i = 0; i < 8; i++) {
        uint32_t raw = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
        ((uint32_t *)digest)[i] = bswap32(raw);
    }
}

static void cleanup(void) {
    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
}

int main(void) {
    sep_outbound_filter_init();

    printf("=== Hash stop/continue multi-part test ===\n");

    /* Part1 must be exactly 64 bytes (SHA-256 block boundary) for hash_stop to work:
     * 1) Packer only flushes on hash_process, not hash_stop; partial words cause idle deadlock.
     * 2) digest_on_blk requires message_length mod 512 == 0; otherwise hmac_done never fires.
     * Part2 can be any length since hash_process triggers packer flush automatically. */
    const uint8_t full_msg[69] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
                                 "Hello";
    const uint8_t part1[64] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
    const uint8_t part2[5] = "Hello";
    uint32_t full_len = 69;
    uint32_t p1_len = 64;
    uint32_t p2_len = 5;

    /* ---- Single-pass hash ---- */
    printf("[Single-pass] Hashing \"Hello World!\"...\n");

    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd_start = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_start.w);

    if (feed_msg(full_msg, full_len) != 0) {
        printf("FAIL: Single-pass feed error\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    hmac__CMD_t cmd_proc = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_proc.w);

    if (wait_for_done_or_idle() != 0) {
        printf("FAIL: Single-pass timeout\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    uint8_t digest_single[32];
    read_digest(digest_single);
    cleanup();

    char hex_single[65];
    to_hex(digest_single, hex_single, 32);
    printf("Single-pass digest: %s\n", hex_single);

    /* ---- Multi-part hash with stop/continue ---- */
    printf("[Multi-part] Hashing \"Hello \" + \"World!\"...\n");

    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg2 = {.w = 0};
    cfg2.f.sha_en = 1;
    cfg2.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg2.w);

    /* hash_start */
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_start.w);

    /* Feed part 1 */
    if (feed_msg(part1, p1_len) != 0) {
        printf("FAIL: Multi-part feed part1 error\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    /* hash_stop */
    hmac__CMD_t cmd_stop = {.f.hash_stop = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_stop.w);

    /* hash_stop at a 64-byte boundary generates hmac_done then asserts hmac_idle.
     * Use wait_for_done_or_idle() to catch either signal. */
    if (wait_for_done_or_idle() != 0) {
        printf("FAIL: Not idle/done after hash_stop\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }
    printf("HMAC idle/done after hash_stop: OK\n");

    /* hash_continue */
    hmac__CMD_t cmd_cont = {.f.hash_continue = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_cont.w);

    /* Feed part 2 */
    if (feed_msg(part2, p2_len) != 0) {
        printf("FAIL: Multi-part feed part2 error\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    /* hash_process */
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd_proc.w);

    if (wait_for_done_or_idle() != 0) {
        printf("FAIL: Multi-part timeout\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }

    uint8_t digest_multi[32];
    read_digest(digest_multi);
    cleanup();

    char hex_multi[65];
    to_hex(digest_multi, hex_multi, 32);
    printf("Multi-part digest: %s\n", hex_multi);

    /* Independent SHA-256 of the exact 69-byte stimulus (64×'A' || "Hello"). */
    static const char expected_hex[] =
        "4705bf4749c8b2cdda9cd82ff0a79861cbc6bbecf0cdc3c5b154722d4785da2e";
    int pass = 1;
    if (strcmp(hex_single, expected_hex) != 0) {
        printf("FAIL: single-pass digest mismatch vs independent SHA-256\n");
        printf("Expected: %s\n", expected_hex);
        pass = 0;
    }
    if (strcmp(hex_multi, expected_hex) != 0) {
        printf("FAIL: multi-part digest mismatch vs independent SHA-256\n");
        printf("Expected: %s\n", expected_hex);
        pass = 0;
    }
    if (memcmp(digest_single, digest_multi, 32) != 0) {
        printf("FAIL: Single-pass and multi-part digests differ\n");
        pass = 0;
    } else {
        printf("Digests match (stop/continue equivalence)\n");
    }

    if (pass) {
        printf("=== PASSED ===\n");
        test_pass(0);
    } else {
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
