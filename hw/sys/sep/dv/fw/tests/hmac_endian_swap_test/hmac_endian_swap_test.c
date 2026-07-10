/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_HMAC_011 (P1) - Endian swap and digest swap test
 *
 * Steps:
 *   1) Hash "abc" with endian_swap=0, digest_swap=0, save raw digest words
 *   2) Hash "abc" with endian_swap=1, digest_swap=0, save raw digest words
 *   3) Verify digests from step 1 and 2 are different
 *   4) Hash "abc" with endian_swap=0, digest_swap=1, save raw digest words
 *   5) Verify digest from step 4 differs from step 1
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

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

/* Write message as 32-bit words so endian_swap takes effect.
 * Per RDL: "A message written to MSG_FIFO one byte at a time will not be
 * affected by this setting." Word-granularity writes are required. */
static int feed_msg_words(const uint32_t *words, uint32_t count) {
    volatile uint32_t *fifo32 =
        (volatile uint32_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR(0);
    for (uint32_t i = 0; i < count; i++) {
        int spins = 0;
        hmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        while (s.f.FIFO_FULL) {
            if (spins++ > 10000) {
                printf("FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo32 = words[i];
    }
    return 0;
}

static int hash_abc_with_swap(uint32_t endian_swap, uint32_t digest_swap, uint32_t digest_out[8]) {
    hmac__INTR_ENABLE_t intr_en = {.f.HMAC_DONE = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.SHA_EN = 1;
    cfg.f.DIGEST_SIZE = 1;
    cfg.f.ENDIAN_SWAP = endian_swap;
    cfg.f.DIGEST_SWAP = digest_swap;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.HASH_START = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    /* Write "abc\x00" as one 32-bit word (0x61626300).
     * endian_swap=1 byte-reverses within the word → SHA sees 0x00636261,
     * yielding a different digest than endian_swap=0. */
    const uint32_t msg_word[] = {0x61626300u};
    if (feed_msg_words(msg_word, 1) != 0) return -1;

    hmac__CMD_t proc = {.f.HASH_PROCESS = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, proc.w);

    if (wait_for_done_or_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        digest_out[i] = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_0_BASE_ADDR(i));
    }

    hmac__CFG_t cfg_off = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg_off.f.SHA_EN = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg_off.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

    return 0;
}

static void print_digest(const char *label, const uint32_t d[8]) {
    printf("%s:", label);
    for (int i = 0; i < 8; i++) printf(" 0x%08x", d[i]);
    printf("\n");
}

int main(void) {
    sep_outbound_filter_init();

    printf("=== TC_HMAC_011: Endian swap and digest swap test ===\n");
    int pass = 1;

    /* Case 1: endian_swap=0, digest_swap=0 (baseline) */
    uint32_t digest_base[8];
    printf("Hash abc: endian_swap=0, digest_swap=0\n");
    if (hash_abc_with_swap(0, 0, digest_base) != 0) {
        printf("FAIL: Baseline hash failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }
    print_digest("Baseline", digest_base);

    /* Case 2: endian_swap=1, digest_swap=0 */
    uint32_t digest_eswap[8];
    printf("Hash abc: endian_swap=1, digest_swap=0\n");
    if (hash_abc_with_swap(1, 0, digest_eswap) != 0) {
        printf("FAIL: Endian-swap hash failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }
    print_digest("Endian-swap", digest_eswap);

    /* Verify baseline vs endian-swap differ */
    int diff_e = 0;
    for (int i = 0; i < 8; i++) {
        if (digest_base[i] != digest_eswap[i]) diff_e = 1;
    }
    if (!diff_e) {
        printf("FAIL: endian_swap=1 produced same raw digest as endian_swap=0\n");
        pass = 0;
    } else {
        printf("OK: endian_swap produces different raw digest\n");
    }

    /* Case 3: endian_swap=0, digest_swap=1 */
    uint32_t digest_dswap[8];
    printf("Hash abc: endian_swap=0, digest_swap=1\n");
    if (hash_abc_with_swap(0, 1, digest_dswap) != 0) {
        printf("FAIL: Digest-swap hash failed\n");
        test_fail(1);
        while (1) {
            __asm__("wfi");
        }
    }
    print_digest("Digest-swap", digest_dswap);

    /* Verify baseline vs digest-swap differ */
    int diff_d = 0;
    for (int i = 0; i < 8; i++) {
        if (digest_base[i] != digest_dswap[i]) diff_d = 1;
    }
    if (!diff_d) {
        printf("FAIL: digest_swap=1 produced same raw digest as digest_swap=0\n");
        pass = 0;
    } else {
        printf("OK: digest_swap produces different raw digest\n");
    }

    if (pass) {
        printf("=== TC_HMAC_011 PASSED ===\n");
        test_pass(0);
    } else {
        printf("FAIL: TC_HMAC_011 endian/digest swap test\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
