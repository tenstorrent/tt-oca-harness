/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 Endian Convert Test.
 *
 * The issue name is hmac_p2_edian_covert_test; keep that spelling for tracking.
 *
 * Verifies endian/digest conversion controls with a word-written message so
 * endian_swap is observable:
 *   1) endian_swap changes the message byte order consumed by SHA.
 *   2) digest_swap byte-swaps each 32-bit raw digest word.
 *   3) combined endian+digest swap matches byte-swapped endian-only output.
 *   4) key_swap is deprecated for production key path, but the CFG bit is writable.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_hmac_p2_edian_covert_test STACK=cgen,sim
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000ffu) << 24) | ((x & 0x0000ff00u) << 8) | ((x & 0x00ff0000u) >> 8) |
           ((x & 0xff000000u) >> 24);
}

static int wait_for_hmac_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__none__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_INTR_STATE_BASE_ADDR)};
        hmac__none__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_STATUS_BASE_ADDR)};
        if (intr.f.HMAC_DONE || status.f.HMAC_IDLE) {
            return 0;
        }
    }

    printf("  Timeout waiting for HMAC completion\n");
    return -1;
}

static void clear_hmac_done(void) {
    hmac__none__INTR_STATE_t clear = {.w = 0};
    clear.f.HMAC_DONE = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_STATE_BASE_ADDR, clear.w);
}

static void cleanup_hmac(void) {
    hmac__none__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR)};
    cfg.f.SHA_EN = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_WIPE_SECRET_BASE_ADDR, 0xffffffffu);
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_ENABLE_BASE_ADDR, 0);
    clear_hmac_done();
}

static int feed_msg_words(const uint32_t *words, uint32_t count) {
    volatile uint32_t *fifo32 =
        (volatile uint32_t *)(uintptr_t)OCH_SEP_TOP_HMAC_NONE_MSG_FIFO_BASE_ADDR(0);

    for (uint32_t i = 0; i < count; i++) {
        int spins = 0;
        hmac__none__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_STATUS_BASE_ADDR)};
        while (status.f.FIFO_FULL) {
            if (spins++ > 10000) {
                printf("  FIFO full timeout at word %u\n", i);
                return -1;
            }
            status.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_STATUS_BASE_ADDR);
        }
        *fifo32 = words[i];
    }

    return 0;
}

static int run_hash(uint32_t endian_swap, uint32_t digest_swap, uint32_t digest_out[8]) {
    clear_hmac_done();

    hmac__none__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.HMAC_DONE = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__none__CFG_t cfg = {.w = 0};
    cfg.f.SHA_EN = 1;
    cfg.f.HMAC_EN = 0;
    cfg.f.DIGEST_SIZE = 1;
    cfg.f.ENDIAN_SWAP = endian_swap;
    cfg.f.DIGEST_SWAP = digest_swap;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

    hmac__none__CMD_t start = {.f.HASH_START = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CMD_BASE_ADDR, start.w);

    const uint32_t msg_words[] = {
        0x01234567u,
        0x89abcdefu,
        0xfedcba98u,
        0x76543210u,
    };
    if (feed_msg_words(msg_words, sizeof(msg_words) / sizeof(msg_words[0])) != 0) {
        return -1;
    }

    uint32_t msg_len = READ_REG(OCH_SEP_TOP_HMAC_NONE_MSG_LENGTH_LOWER_BASE_ADDR);
    if (msg_len != sizeof(msg_words) * 8u) {
        printf("  FAIL: MSG_LENGTH=%u expected=%u\n", msg_len, (unsigned)(sizeof(msg_words) * 8u));
        return -1;
    }

    hmac__none__CMD_t process = {.f.HASH_PROCESS = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CMD_BASE_ADDR, process.w);
    if (wait_for_hmac_done() != 0) {
        return -1;
    }

    for (int i = 0; i < 8; i++) {
        digest_out[i] = READ_REG(OCH_SEP_TOP_HMAC_NONE_DIGEST_0_BASE_ADDR(i));
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

    hmac__none__CFG_t cfg = {.w = 0};
    cfg.f.SHA_EN = 1;
    cfg.f.DIGEST_SIZE = 1;
    cfg.f.KEY_SWAP = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

    hmac__none__CFG_t rb = {.w = READ_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR)};
    printf("  CFG write=0x%08x read=0x%08x key_swap=%u\n", cfg.w, rb.w, rb.f.KEY_SWAP);

    cfg.f.SHA_EN = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_NONE_CFG_BASE_ADDR, cfg.w);

    if (rb.f.KEY_SWAP != 1) {
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
