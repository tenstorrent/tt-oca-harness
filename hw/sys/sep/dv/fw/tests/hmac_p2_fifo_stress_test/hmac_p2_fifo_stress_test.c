/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 FIFO Stress Test.
 *
 * Phase A proves MSG_FIFO accepts a word burst via MSG_LENGTH, then drains.
 * Phase B streams a 2048-byte deterministic pseudo-random message through
 * MSG_FIFO in pseudo-random chunk sizes, verifies exact message length,
 * STATUS.fifo_empty after drain, and the final SHA-256 digest.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"
#include "test_completion.h"
#define MSG_LEN_BYTES 2048u

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000ffu) << 24) | ((x & 0x0000ff00u) << 8) | ((x & 0x00ff0000u) >> 8) |
           ((x & 0xff000000u) >> 24);
}

static uint8_t msg_byte(uint32_t idx) {
    return (uint8_t)((idx * 13u + 7u) & 0xffu);
}

static void spin_delay(uint32_t cycles) {
    for (volatile uint32_t i = 0; i < cycles; i++) {
        __asm__ volatile("nop");
    }
}

static int wait_for_done_or_idle(void) {
    int timeout = 2000000;
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

static void read_digest_hex(char *hex_out) {
    static const char hex_chars[] = "0123456789abcdef";

    for (int word = 0; word < 8; word++) {
        uint32_t raw = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(word));
        uint32_t digest_word = bswap32(raw);
        for (int byte = 0; byte < 4; byte++) {
            uint8_t value = (uint8_t)(digest_word >> (byte * 8));
            int idx = word * 8 + byte * 2;
            hex_out[idx + 0] = hex_chars[(value >> 4) & 0xf];
            hex_out[idx + 1] = hex_chars[value & 0xf];
        }
    }
    hex_out[64] = '\0';
}

static void hmac_cfg_sha256_start(void) {
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);
}

static int prove_fifo_accept_then_drain(void) {
    /*
     * Separate hash: prove MSG_FIFO accepts a word burst via MSG_LENGTH, then
     * process/drain. fifo_full@32 is not required under CPU MMIO Pass-through.
     */
    volatile uint32_t *fifo32 = (volatile uint32_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    const uint32_t words = 32u;
    uint32_t max_depth = 0;
    int full_seen = 0;

    hmac_cfg_sha256_start();

    for (uint32_t i = 0; i < words; i++) {
        *fifo32 = 0xC0000000u | i;
        hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (status.f.fifo_depth > max_depth) max_depth = status.f.fifo_depth;
        if (status.f.fifo_full) full_seen = 1;
    }

    uint32_t msg_bits = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR);
    printf("  Accept probe: words=%u MSG_LENGTH=%u full_seen=%u max_depth=%u\n", words, msg_bits,
           full_seen, max_depth);
    if (msg_bits != words * 32u) {
        printf("  FAIL: MSG_LENGTH mismatch after FIFO burst\n");
        hmac__CMD_t process_fail = {.f.hash_process = 1};
        WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, process_fail.w);
        (void)wait_for_done_or_idle();
        return -1;
    }

    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);
    if (wait_for_done_or_idle() != 0) {
        return -1;
    }

    hmac__INTR_STATE_t clear = {.w = 0};
    clear.f.hmac_done = 1;
    clear.f.fifo_empty = 1;
    clear.f.hmac_err = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    return 0;
}

static int stream_message(void) {
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    uint32_t pos = 0;
    uint32_t chunks = 0;
    uint32_t full_waits = 0;
    uint32_t full_seen = 0;
    uint32_t empty_seen = 0;
    uint32_t max_depth = 0;

    while (pos < MSG_LEN_BYTES) {
        uint32_t chunk = ((pos * 17u + 23u) % 97u) + 1u;
        if (chunk > MSG_LEN_BYTES - pos) {
            chunk = MSG_LEN_BYTES - pos;
        }

        for (uint32_t i = 0; i < chunk; i++) {
            int spins = 0;
            hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
            while (status.f.fifo_full) {
                full_seen = 1;
                full_waits++;
                if (spins++ > 100000) {
                    printf("  FIFO full timeout at byte %u\n", pos);
                    return -1;
                }
                status.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR);
            }

            if (status.f.fifo_empty) {
                empty_seen++;
            }
            if (status.f.fifo_depth > max_depth) {
                max_depth = status.f.fifo_depth;
            }

            *fifo8 = msg_byte(pos);
            pos++;
        }

        chunks++;
        spin_delay((chunks * 11u) & 0x3fu);
    }

    hmac__STATUS_t final_status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    if (final_status.f.fifo_depth > max_depth) {
        max_depth = final_status.f.fifo_depth;
    }

    printf("  Streamed %u bytes in %u chunks\n", pos, chunks);
    printf(
        "  FIFO stats: full_seen=%u full_waits=%u empty_samples=%u max_depth=%u final_depth=%u\n",
        full_seen, full_waits, empty_seen, max_depth, final_status.f.fifo_depth);

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("HMAC P2 FIFO Stress Test\n");
    printf("========================================\n");

    int pass = 1;

    hmac__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    printf("Step 1: Prove MSG_FIFO accept + drain (separate hash)\n");
    if (prove_fifo_accept_then_drain() != 0) {
        pass = 0;
    }

    printf("Step 2: Stream pseudo-random 2048-byte message\n");
    hmac_cfg_sha256_start();
    if (pass && stream_message() != 0) {
        pass = 0;
    }

    uint32_t msg_len_lower = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR);
    uint32_t msg_len_upper = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR);
    printf("  MSG_LENGTH lower=%u upper=%u expected=%u\n", msg_len_lower, msg_len_upper,
           MSG_LEN_BYTES * 8u);
    if (msg_len_lower != MSG_LEN_BYTES * 8u || msg_len_upper != 0) {
        printf("  FAIL: message length mismatch\n");
        pass = 0;
    }

    printf("Step 3: hash_process and wait for completion\n");
    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);
    if (wait_for_done_or_idle() != 0) {
        pass = 0;
    }

    hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    printf("  STATUS=0x%08x idle=%u empty=%u full=%u depth=%u\n", status.w, status.f.hmac_idle,
           status.f.fifo_empty, status.f.fifo_full, status.f.fifo_depth);
    if (!status.f.hmac_idle || !status.f.fifo_empty) {
        printf("  FAIL: HMAC did not return idle/empty after stress\n");
        pass = 0;
    }
    /* Post-stress proof is STATUS idle/empty + digest. */

    char got_hex[65];
    read_digest_hex(got_hex);
    const char *expected_hex = "6228ae9897dbc6790f79823e9f8fc92dd3f07ade353de87fbb7e0cbe485be3f1";
    printf("  Digest:   %s\n", got_hex);
    printf("  Expected: %s\n", expected_hex);
    if (strcmp(got_hex, expected_hex) != 0) {
        printf("  FAIL: digest mismatch\n");
        pass = 0;
    }

    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC P2 FIFO STRESS TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC P2 FIFO STRESS TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
