/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * hamc_p1_extendmode_test
 *
 * Verifies HMAC extended SHA-2 modes and 1024-bit key handling:
 *   - HMAC-SHA384 with 512-bit and 1024-bit keys
 *   - HMAC-SHA512 with 512-bit and 1024-bit keys
 *
 * The directory name keeps the reference suite's spelling ("hamc").
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

#define HMAC_DIGEST_SHA384_WORDS 12
#define HMAC_DIGEST_SHA512_WORDS 16
#define HMAC_KEY_512_WORDS 16
#define HMAC_KEY_1024_WORDS 32

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000FFu) << 24) | ((x & 0x0000FF00u) << 8) | ((x & 0x00FF0000u) >> 8) |
           ((x & 0xFF000000u) >> 24);
}

static void to_hex(const uint8_t *in, char *out, int len) {
    static const char *hex = "0123456789abcdef";

    for (int i = 0; i < len; i++) {
        out[2 * i + 0] = hex[(in[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[in[i] & 0xF];
    }
    out[2 * len] = '\0';
}

static int wait_for_done(void) {
    int timeout = 2000000;

    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        if (intr.f.hmac_done) {
            WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, intr.w);
            return 0;
        }
    }

    printf("FAIL: Timeout waiting for HMAC done\n");
    return -1;
}

static int feed_msg(const uint8_t *data, uint32_t len) {
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;

    for (uint32_t i = 0; i < len; i++) {
        int spins = 0;
        hmac__STATUS_t s = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};

        while (s.f.fifo_full) {
            if (spins++ > 10000) {
                printf("FAIL: FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo8 = data[i];
    }

    return 0;
}

static void write_repeated_key(uint32_t key_words) {
    for (uint32_t i = 0; i < key_words; i++) {
        WRITE_REG(SEP_TOP_HMAC_KEY_BASE_ADDR(i), 0x0B0B0B0Bu);
    }
}

static void cleanup_hmac(void) {
    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};

    cfg.f.sha_en = 0;
    cfg.f.hmac_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
}

static int run_hmac_case(const char *name, uint32_t digest_size, uint32_t key_length,
                         uint32_t key_words, uint32_t digest_words, const char *expected) {
    const uint8_t msg[] = "Hi There";
    uint32_t digest[HMAC_DIGEST_SHA512_WORDS];
    char got[129];

    printf("\n--- %s ---\n", name);
    cleanup_hmac();
    write_repeated_key(key_words);

    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 1;
    cfg.f.sha_en = 1;
    cfg.f.endian_swap = 0;
    cfg.f.digest_swap = 0;
    cfg.f.digest_size = digest_size;
    cfg.f.key_length = key_length;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CFG_t rb = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    if (rb.f.digest_size != digest_size || rb.f.key_length != key_length) {
        printf("FAIL: CFG readback digest_size=0x%x key_length=0x%x\n", rb.f.digest_size,
               rb.f.key_length);
        return 0;
    }

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    if (feed_msg(msg, sizeof(msg) - 1) != 0) {
        return 0;
    }

    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);

    if (wait_for_done() != 0) {
        return 0;
    }

    for (uint32_t i = 0; i < digest_words; i++) {
        uint32_t raw = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
        digest[i] = bswap32(raw);
    }

    to_hex((const uint8_t *)digest, got, digest_words * 4);
    printf("Digest:   %s\n", got);
    printf("Expected: %s\n", expected);

    if (strcmp(got, expected) != 0) {
        printf("FAIL: Digest mismatch for %s\n", name);
        return 0;
    }

    printf("PASS: %s\n", name);
    return 1;
}

int main(void) {
    int pass = 1;

    sep_outbound_filter_init();

    printf("=== hamc_p1_extendmode_test: HMAC SHA-384/512 extended modes ===\n");

    pass &= run_hmac_case("HMAC-SHA384 key_length=512", 0x2, 0x08, HMAC_KEY_512_WORDS,
                          HMAC_DIGEST_SHA384_WORDS,
                          "51b2151ae771770f36cc6c5d63de41fcfebab0900a22b41cb81e12209215337e"
                          "5d5384201f6dc3ca9f92764c503380e6");

    pass &= run_hmac_case("HMAC-SHA384 key_length=1024", 0x2, 0x10, HMAC_KEY_1024_WORDS,
                          HMAC_DIGEST_SHA384_WORDS,
                          "526be3f121924da767b31c674f42eec1b6e0fe7e448cc9430e485978717e4b45"
                          "e6c58e0747d9874e5b6d663cebbe73f4");

    pass &= run_hmac_case("HMAC-SHA512 key_length=512", 0x4, 0x08, HMAC_KEY_512_WORDS,
                          HMAC_DIGEST_SHA512_WORDS,
                          "637edc6e01dce7e6742a99451aae82df23da3e92439e590e43e761b33e910fb8"
                          "ac2878ebd5803f6f0b61dbce5e251ff8789a4722c1be65aea45fd464e89f8f5b");

    pass &= run_hmac_case("HMAC-SHA512 key_length=1024", 0x4, 0x10, HMAC_KEY_1024_WORDS,
                          HMAC_DIGEST_SHA512_WORDS,
                          "e0853e8ef09d70a6ae8431a46c5c87590e12ad57f6ab11504a15bf500b431c11"
                          "2501952fe1fdcdc6464e3b16d26a070252abd243a0efafb5cd46fc11c6934658");

    cleanup_hmac();

    if (pass) {
        printf("=== hamc_p1_extendmode_test PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== hamc_p1_extendmode_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
