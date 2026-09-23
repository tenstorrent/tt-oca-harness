/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC SHA-384 and SHA-512 Test
 *
 * Verifies SHA-384 and SHA-512 digest computation against NIST FIPS 180-4
 * known-answer vectors for message "abc".
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

static int wait_for_completion(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) {
            break;
        }
    }
    if (timeout <= 0) {
        printf("Timeout waiting for HMAC completion\n");
        return -1;
    }

    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.hmac_done) {
        hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
        WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    }
    return 0;
}

static int feed_message_bytes(const uint8_t *msg, uint32_t len) {
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    for (uint32_t i = 0; i < len; i++) {
        hmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        int spins = 0;
        while (s.f.fifo_full) {
            if (spins++ > 10000) {
                printf("  FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo8 = msg[i];
    }
    return 0;
}

static void digest_to_hex(uint32_t nwords, char *hex_out) {
    static const char hex_chars[] = "0123456789abcdef";
    for (uint32_t word = 0; word < nwords; word++) {
        uint32_t raw = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_BASE_ADDR(word));
        uint32_t digest_word = bswap32(raw);
        for (int byte = 0; byte < 4; byte++) {
            uint8_t value = (uint8_t)(digest_word >> (byte * 8));
            int idx = (int)(word * 8u + (uint32_t)byte * 2u);
            hex_out[idx + 0] = hex_chars[(value >> 4) & 0xf];
            hex_out[idx + 1] = hex_chars[value & 0xf];
        }
    }
    hex_out[nwords * 8u] = '\0';
}

static int run_sha_case(const char *name, uint32_t digest_size, uint32_t nwords,
                        const char *expected_hex) {
    printf("\n--- Testing %s ---\n", name);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 1;
    cfg.f.digest_size = digest_size;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    printf("  CFG: 0x%08x\n", cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    const uint8_t msg[] = {'a', 'b', 'c'};
    if (feed_message_bytes(msg, 3) != 0) return -1;

    cmd.w = 0;
    cmd.f.hash_process = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    printf("  Processing hash...\n");

    if (wait_for_completion() != 0) return -1;
    printf("  Hash completed\n");

    char got_hex[129];
    if (nwords * 8u >= sizeof(got_hex)) return -1;
    digest_to_hex(nwords, got_hex);

    printf("  Digest: %s\n", got_hex);
    printf("  Expected: %s\n", expected_hex);
    if (strcmp(got_hex, expected_hex) != 0) {
        printf("  FAIL: %s digest mismatch\n", name);
        return -1;
    }
    printf("  PASS: %s matches NIST vector\n", name);
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n====================================================\n");
    printf("HMAC SHA-384 and SHA-512 Test\n");
    printf("====================================================\n");

    int pass = 1;

    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    /* NIST FIPS 180-4 SHA-384("abc") */
    const char *sha384_hex = "cb00753f45a35e8bb5a03d699ac65007272c32ab0eded1631a8b605a43ff5bed"
                             "8086072ba1e7cc2358baeca134c825a7";
    if (run_sha_case("SHA-384", SEP_HMAC_DIGEST_SIZE_SHA2_384, 12, sha384_hex) != 0) {
        pass = 0;
    }

    /* NIST FIPS 180-4 SHA-512("abc") */
    const char *sha512_hex = "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
                             "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f";
    if (run_sha_case("SHA-512", SEP_HMAC_DIGEST_SIZE_SHA2_512, 16, sha512_hex) != 0) {
        pass = 0;
    }

    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

    printf("\n====================================================\n");
    if (pass) {
        printf("=== HMAC SHA-384/SHA-512 TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC SHA-384/SHA-512 TEST FAILED ===\n");
        test_fail(0);
    }
    printf("====================================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
