/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 Endian Convert Test.
 *
 * Verifies endian/digest conversion controls with a word-written message so
 * endian_swap is observable:
 *   1) endian_swap changes the message byte order consumed by SHA.
 *   2) digest_swap byte-swaps each 32-bit raw digest word.
 *   3) combined endian+digest swap matches byte-swapped endian-only output.
 *   4) key_swap is deprecated for production key path, but the CFG bit is writable.
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"
#include "test_completion.h"

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000ffu) << 24) | ((x & 0x0000ff00u) << 8) | ((x & 0x00ff0000u) >> 8) |
           ((x & 0xff000000u) >> 24);
}

static int wait_for_hmac_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || status.f.hmac_idle) {
            return 0;
        }
    }

    printf("  Timeout waiting for HMAC completion\n");
    return -1;
}

static void clear_hmac_done(void) {
    hmac__INTR_STATE_t clear = {.w = 0};
    clear.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
}

static void cleanup_hmac(void) {
    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
    clear_hmac_done();
}

static int feed_msg_words(const uint32_t *words, uint32_t count) {
    volatile uint32_t *fifo32 = (volatile uint32_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;

    for (uint32_t i = 0; i < count; i++) {
        int spins = 0;
        hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        while (status.f.fifo_full) {
            if (spins++ > 10000) {
                printf("  FIFO full timeout at word %u\n", i);
                return -1;
            }
            status.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo32 = words[i];
    }

    return 0;
}

static int run_hash(uint32_t endian_swap, uint32_t digest_swap, uint32_t digest_out[8]) {
    clear_hmac_done();

    hmac__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    cfg.f.endian_swap = endian_swap;
    cfg.f.digest_swap = digest_swap;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    const uint32_t msg_words[] = {
        0x01234567u,
        0x89abcdefu,
        0xfedcba98u,
        0x76543210u,
    };
    if (feed_msg_words(msg_words, sizeof(msg_words) / sizeof(msg_words[0])) != 0) {
        return -1;
    }

    uint64_t expected_bits = (uint64_t)sizeof(msg_words) * 8ull;
    uint32_t msg_lo = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR);
    uint32_t msg_hi = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR);
    if (msg_lo != (uint32_t)expected_bits || msg_hi != (uint32_t)(expected_bits >> 32)) {
        printf("  FAIL: MSG_LENGTH=%u:%u expected=%u:%u\n", msg_lo, msg_hi, (uint32_t)expected_bits,
               (uint32_t)(expected_bits >> 32));
        return -1;
    }

    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);
    if (wait_for_hmac_done() != 0) {
        return -1;
    }

    for (int i = 0; i < 8; i++) {
        digest_out[i] = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
    }

    cleanup_hmac();
    return 0;
}

static void print_digest(const char *label, const uint32_t digest[8]) {
    printf("  %s:", label);
    for (int i = 0; i < 8; i++) {
        printf(" 0x%08x", digest[i]);
    }
    printf("\n");
}

static int digest_equal(const uint32_t a[8], const uint32_t b[8]) {
    for (int i = 0; i < 8; i++) {
        if (a[i] != b[i]) {
            return 0;
        }
    }
    return 1;
}

static int digest_is_bswap_of(const uint32_t swapped[8], const uint32_t raw[8]) {
    for (int i = 0; i < 8; i++) {
        if (swapped[i] != bswap32(raw[i])) {
            printf("  Word %d mismatch: got=0x%08x expected_bswap=0x%08x raw=0x%08x\n", i,
                   swapped[i], bswap32(raw[i]), raw[i]);
            return 0;
        }
    }
    return 1;
}

static int check_key_swap_cfg_bit(void) {
    printf("\nStep 5: key_swap CFG bit readback (deprecated path)\n");

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    cfg.f.key_swap = 1;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CFG_t rb = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    printf("  CFG write=0x%08x read=0x%08x key_swap=%u\n", cfg.w, rb.w, rb.f.key_swap);

    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    if (rb.f.key_swap != 1) {
        printf("  FAIL: key_swap CFG bit did not read back as writable\n");
        return -1;
    }

    printf("  INFO: key_swap is deprecated for production key path; readback only checked\n");
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC P2 Endian Convert Test\n");
    printf("========================================\n");

    int pass = 1;
    uint32_t base[8];
    uint32_t endian_only[8];
    uint32_t digest_only[8];
    uint32_t both[8];

    printf("\nStep 1: baseline endian_swap=0 digest_swap=0\n");
    if (run_hash(0, 0, base) != 0) {
        pass = 0;
    }
    print_digest("baseline", base);

    printf("\nStep 2: endian_swap=1 digest_swap=0\n");
    if (pass && run_hash(1, 0, endian_only) != 0) {
        pass = 0;
    }
    print_digest("endian_only", endian_only);

    printf("\nStep 3: endian_swap=0 digest_swap=1\n");
    if (pass && run_hash(0, 1, digest_only) != 0) {
        pass = 0;
    }
    print_digest("digest_only", digest_only);

    printf("\nStep 4: endian_swap=1 digest_swap=1\n");
    if (pass && run_hash(1, 1, both) != 0) {
        pass = 0;
    }
    print_digest("both", both);

    /* Independent SHA-256 of the four word stimulus under each CFG combo. */
    static const uint32_t expected_base[8] = {0xff107f9au, 0x1a123b36u, 0x3b5480a5u, 0x1ea1aec4u,
                                              0xe79dafc0u, 0x2be71119u, 0x780b4aa6u, 0x98c57fefu};
    static const uint32_t expected_endian[8] = {0x411d3f1du, 0x2390ff3fu, 0x482ac8dfu, 0x4e730780u,
                                                0xbb081a19u, 0x2f283d2fu, 0x373138fdu, 0x101dc8feu};
    static const uint32_t expected_digest[8] = {0x9a7f10ffu, 0x363b121au, 0xa580543bu, 0xc4aea11eu,
                                                0xc0af9de7u, 0x1911e72bu, 0xa64a0b78u, 0xef7fc598u};
    static const uint32_t expected_both[8] = {0x1d3f1d41u, 0x3fff9023u, 0xdfc82a48u, 0x8007734eu,
                                              0x191a08bbu, 0x2f3d282fu, 0xfd383137u, 0xfec81d10u};

    if (pass && !digest_equal(base, expected_base)) {
        printf("  FAIL: baseline digest mismatch vs independent SHA-256\n");
        pass = 0;
    }
    if (pass && !digest_equal(endian_only, expected_endian)) {
        printf("  FAIL: endian_only digest mismatch vs independent SHA-256\n");
        pass = 0;
    }
    if (pass && !digest_equal(digest_only, expected_digest)) {
        printf("  FAIL: digest_only mismatch vs independent SHA-256\n");
        pass = 0;
    }
    if (pass && !digest_equal(both, expected_both)) {
        printf("  FAIL: combined-swap digest mismatch vs independent SHA-256\n");
        pass = 0;
    }
    if (pass && digest_equal(base, endian_only)) {
        printf("  FAIL: endian_swap did not change raw digest for word writes\n");
        pass = 0;
    }
    if (pass && !digest_is_bswap_of(digest_only, base)) {
        printf("  FAIL: digest_swap output is not byte-swapped baseline digest\n");
        pass = 0;
    }
    if (pass && !digest_is_bswap_of(both, endian_only)) {
        printf("  FAIL: combined swap output is not byte-swapped endian-only digest\n");
        pass = 0;
    }
    if (pass && check_key_swap_cfg_bit() != 0) {
        pass = 0;
    }

    cleanup_hmac();

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC P2 ENDIAN CONVERT TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC P2 ENDIAN CONVERT TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
