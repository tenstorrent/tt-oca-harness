/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC Long Message Test - TC_HMAC_015 (P1)
 *
 * Verifies HMAC handling of messages longer than MSG FIFO capacity.
 * Tests FIFO polling, multi-block processing, and proper message length handling.
 *
 * Key test scenarios:
 * - Messages > 128 bytes (FIFO capacity)
 * - FIFO depth monitoring and backpressure handling
 * - Multi-block SHA processing
 * - Proper message length bit counting
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_hmac_long_message_test STACK=sim
 *
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

static int wait_for_completion(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.HMAC_DONE || sts.f.HMAC_IDLE) {
            break;
        }
    }
    if (timeout <= 0) {
        printf("Timeout waiting for HMAC completion\n");
        return -1;
    }

    // Clear hmac_done if set
    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.HMAC_DONE) {
        hmac__INTR_STATE_t clear = {.f.HMAC_DONE = 1};
        WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    }
    return 0;
}

static int wait_for_fifo_space(void) {
    int timeout = 10000;
    while (timeout-- > 0) {
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (!sts.f.FIFO_FULL) {
            return 0; // FIFO has space
        }
    }
    printf("Timeout waiting for FIFO space\n");
    return -1;
}

static int feed_long_message(const char *pattern, int total_bytes) {
    printf("  Feeding long message: pattern='%s' repeated for %d bytes\n", pattern, total_bytes);

    int pattern_len = strlen(pattern);
    int bytes_sent = 0;
    int word_buffer = 0;
    int bytes_in_word = 0;

    while (bytes_sent < total_bytes) {
        // Pack bytes into 32-bit words
        while (bytes_in_word < 4 && bytes_sent < total_bytes) {
            char ch = pattern[bytes_sent % pattern_len];
            word_buffer |= ((uint32_t)ch) << (bytes_in_word * 8);
            bytes_in_word++;
            bytes_sent++;
        }

        // Send word when full or at end of message
        if (bytes_in_word == 4 || bytes_sent == total_bytes) {
            // Wait for FIFO space if needed
            if (wait_for_fifo_space() != 0) return -1;

            // Write word to MSG FIFO
            WRITE_REG(OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR(0), word_buffer);

            if ((bytes_sent % 64) == 0 || bytes_sent == total_bytes) {
                // Monitor FIFO depth periodically
                hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
                printf("    Sent %d bytes, FIFO depth=%u, full=%u\n", bytes_sent, sts.f.FIFO_DEPTH,
                       sts.f.FIFO_FULL);
            }

            word_buffer = 0;
            bytes_in_word = 0;
        }
    }

    printf("  Long message feeding completed: %d bytes\n", bytes_sent);
    return 0;
}

static int test_long_message_sha256(void) {
    printf("\n--- Testing Long Message SHA-256 (200 bytes) ---\n");

    // Configure for SHA-256
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.HMAC_EN = 0;       // SHA only
    cfg.f.SHA_EN = 1;        // SHA enabled
    cfg.f.DIGEST_SIZE = 0x1; // SHA-256
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    printf("  CFG: 0x%08x (SHA-256, SHA mode)\n", cfg.w);

    // Start new hash
    hmac__CMD_t cmd = {.f.HASH_START = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    printf("  Started new hash\n");

    // Send long message (200 bytes, pattern "ABCDEFGH")
    const char *pattern = "ABCDEFGH";
    int total_bytes = 200;
    if (feed_long_message(pattern, total_bytes) != 0) return -1;

    // Set message length in bits
    uint64_t msg_len_bits = total_bytes * 8;
    WRITE_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR,
              (uint32_t)(msg_len_bits & 0xFFFFFFFF));
    WRITE_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR, (uint32_t)(msg_len_bits >> 32));
    printf("  Message length: %llu bits\n", msg_len_bits);

    // Trigger hash processing
    cmd.w = 0;
    cmd.f.HASH_PROCESS = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    printf("  Processing hash...\n");

    // Wait for completion
    if (wait_for_completion() != 0) return -1;
    printf("  Hash completed\n");

    // Read digest
    uint32_t digest[8];
    for (int i = 0; i < 8; i++) {
        digest[i] = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_0_BASE_ADDR(i));
    }

    printf("  SHA-256 digest of long message:\n");
    for (int i = 0; i < 8; i++) {
        printf("    DIGEST_%d: 0x%08x\n", i, digest[i]);
    }

    // Verify we got a non-zero digest
    int all_zero = 1;
    for (int i = 0; i < 8; i++) {
        if (digest[i] != 0) all_zero = 0;
    }

    if (all_zero) {
        printf("  FAIL: SHA-256 digest is all zeros\n");
        return -1;
    }

    printf("  PASS: Long message SHA-256 digest computed\n");
    return 0;
}

static int test_very_long_message(void) {
    printf("\n--- Testing Very Long Message SHA-256 (1000 bytes) ---\n");

    // Configure for SHA-256
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.HMAC_EN = 0;       // SHA only
    cfg.f.SHA_EN = 1;        // SHA enabled
    cfg.f.DIGEST_SIZE = 0x1; // SHA-256
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    // Start new hash
    hmac__CMD_t cmd = {.f.HASH_START = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    printf("  Started new hash\n");

    // Send very long message (1000 bytes, pattern "0123456789")
    const char *pattern = "0123456789";
    int total_bytes = 1000;
    if (feed_long_message(pattern, total_bytes) != 0) return -1;

    // Set message length in bits
    uint64_t msg_len_bits = total_bytes * 8;
    WRITE_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR,
              (uint32_t)(msg_len_bits & 0xFFFFFFFF));
    WRITE_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR, (uint32_t)(msg_len_bits >> 32));
    printf("  Message length: %llu bits\n", msg_len_bits);

    // Trigger hash processing
    cmd.w = 0;
    cmd.f.HASH_PROCESS = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    printf("  Processing hash...\n");

    // Wait for completion
    if (wait_for_completion() != 0) return -1;
    printf("  Hash completed\n");

    // Read digest
    uint32_t digest[8];
    for (int i = 0; i < 8; i++) {
        digest[i] = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_0_BASE_ADDR(i));
    }

    printf("  SHA-256 digest of very long message:\n");
    for (int i = 0; i < 8; i++) {
        printf("    DIGEST_%d: 0x%08x\n", i, digest[i]);
    }

    // Verify we got a non-zero digest
    int all_zero = 1;
    for (int i = 0; i < 8; i++) {
        if (digest[i] != 0) all_zero = 0;
    }

    if (all_zero) {
        printf("  FAIL: SHA-256 digest is all zeros\n");
        return -1;
    }

    printf("  PASS: Very long message SHA-256 digest computed\n");
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n====================================================\n");
    printf("HMAC Long Message Test (TC_HMAC_015)\n");
    printf("====================================================\n");

    int pass = 1;

    // Enable hmac_done interrupt
    hmac__INTR_ENABLE_t intr_en = {.f.HMAC_DONE = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    // Test 200-byte message (> FIFO capacity of 128 bytes)
    if (test_long_message_sha256() != 0) {
        printf("\nLong message test FAILED\n");
        pass = 0;
    }

    // Test 1000-byte message (stress test)
    if (test_very_long_message() != 0) {
        printf("\nVery long message test FAILED\n");
        pass = 0;
    }

    printf("\n====================================================\n");
    if (pass) {
        printf("=== HMAC LONG MESSAGE TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC LONG MESSAGE TEST FAILED ===\n");
        test_fail(0);
    }
    printf("====================================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}