/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_hmac_sha256.c
 * @brief SHA-256 + HMAC-SHA256 library tests (FIPS 180-4 / RFC 4231 vectors).
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_hmac_sha256
 */

#include "test_common.h"
#include "rom_boot.h"
#include "rom_sha256.h"
#include "rom_hmac.h"
#include "rom_secutil.h"

#include "sha256_vectors.h"
#include "hmac_sha256_vectors.h"

/* Skip boot/unrecoverable wipe so the test boots quickly (see test_rom_crc.c). */
int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/* Plain (non-constant-time) byte compare for golden-vector checks. */
static int bytes_equal(const uint8_t *a, const uint8_t *b, uint32_t n) {
    for (uint32_t i = 0u; i < n; i++) {
        if (a[i] != b[i]) return 0;
    }
    return 1;
}

static int bytes_all_zero(const uint8_t *data, uint32_t n) {
    for (uint32_t i = 0u; i < n; i++) {
        if (data[i] != 0u) return 0;
    }
    return 1;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(2000000u)) {
        TEST_FAIL("Failed to set test timeout");
    }

    TEST_SUBTEST_START("SHA-256 FIPS/CAVP golden vectors");
    {
        for (uint32_t i = 0u; i < (uint32_t)SHA256_NUM_VECTORS; i++) {
            const struct sha256_test_vector *v = &sha256_test_vectors[i];
            struct rom_sha256_ctx ctx;
            uint8_t *digest;

            rom_sha256_init(&ctx);
            rom_sha256_update(&ctx, v->message, (uint32_t)v->message_len);
            digest = rom_sha256_final(&ctx);

            TEST_ASSERT(digest != NULL, "%s: digest was NULL", v->name);
            TEST_ASSERT(bytes_equal(digest, v->expected_digest, ROM_SHA256_DIGEST_SIZE),
                        "%s: SHA-256 digest mismatch", v->name);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("SHA-256 incremental update matches one-shot");
    {
        /* Split "abc...q" (56 bytes) into two updates and compare to the vector. */
        const struct sha256_test_vector *v = &sha256_test_vectors[2]; /* 56-byte vector */
        struct rom_sha256_ctx ctx;
        uint8_t *digest;

        rom_sha256_init(&ctx);
        rom_sha256_update(&ctx, v->message, 1u);
        rom_sha256_update(&ctx, v->message + 1u, (uint32_t)v->message_len - 1u);
        digest = rom_sha256_final(&ctx);

        TEST_ASSERT(digest != NULL, "incremental digest NULL");
        TEST_ASSERT(bytes_equal(digest, v->expected_digest, ROM_SHA256_DIGEST_SIZE),
                    "incremental SHA-256 mismatch");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("HMAC-SHA256 RFC 4231 golden vectors");
    {
        for (uint32_t i = 0u; i < (uint32_t)HMAC_SHA256_NUM_VECTORS; i++) {
            const struct hmac_sha256_test_vector *v = &hmac_sha256_test_vectors[i];
            uint8_t out[ROM_SHA256_DIGEST_SIZE];

            TEST_ASSERT(rom_hmac_sha256(out, v->key, (uint32_t)v->key_len, v->data,
                                        (uint32_t)v->data_len) == 0,
                        "%s: HMAC returned failure", v->name);

            TEST_ASSERT(bytes_equal(out, v->expected_mac, ROM_SHA256_DIGEST_SIZE),
                        "%s: HMAC mismatch", v->name);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("HMAC-SHA256 empty message yields non-zero MAC");
    {
        uint8_t out[ROM_SHA256_DIGEST_SIZE];
        int all_zero = 1;

        rom_hmac_sha256(out, hmac_vec1_key, 20u, NULL, 0u);
        for (uint32_t i = 0u; i < (uint32_t)ROM_SHA256_DIGEST_SIZE; i++) {
            if (out[i] != 0u) {
                all_zero = 0;
                break;
            }
        }
        TEST_ASSERT(!all_zero, "empty-message MAC was all zero");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("HMAC-SHA256 rejects invalid pointer/length pairs");
    {
        static const uint8_t key[] = "key";
        static const uint8_t data[] = "data";
        uint8_t out[ROM_SHA256_DIGEST_SIZE];

        TEST_ASSERT(rom_hmac_sha256(out, NULL, 1u, data, (uint32_t)(sizeof(data) - 1u)) == -1,
                    "NULL non-empty key was accepted");
        TEST_ASSERT(bytes_all_zero(out, ROM_SHA256_DIGEST_SIZE), "invalid key did not zero output");

        TEST_ASSERT(rom_hmac_sha256(out, key, (uint32_t)(sizeof(key) - 1u), NULL, 1u) == -1,
                    "NULL non-empty message was accepted");
        TEST_ASSERT(bytes_all_zero(out, ROM_SHA256_DIGEST_SIZE),
                    "invalid message did not zero output");

        out[0] = 0xa5u;
        TEST_ASSERT(rom_hmac_sha256(out, key, (uint32_t)(sizeof(key) - 1u), data,
                                    ROM_HMAC_MAX_MESSAGE_BYTES + 1u) == -1,
                    "oversized message was accepted");
        TEST_ASSERT(bytes_all_zero(out, ROM_SHA256_DIGEST_SIZE),
                    "oversized message did not zero output");

        TEST_ASSERT(rom_hmac_sha256(NULL, key, (uint32_t)(sizeof(key) - 1u), data,
                                    (uint32_t)(sizeof(data) - 1u)) == -1,
                    "NULL output was accepted");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("HMAC-SHA256 determinism and key/data sensitivity");
    {
        static const uint8_t key[] = "secret key";
        static const uint8_t key2[] = "different key";
        static const uint8_t data[] = "message to authenticate";
        static const uint8_t data2[] = "different message";
        uint8_t out1[ROM_SHA256_DIGEST_SIZE];
        uint8_t out2[ROM_SHA256_DIGEST_SIZE];

        rom_hmac_sha256(out1, key, (uint32_t)(sizeof(key) - 1u), data,
                        (uint32_t)(sizeof(data) - 1u));
        rom_hmac_sha256(out2, key, (uint32_t)(sizeof(key) - 1u), data,
                        (uint32_t)(sizeof(data) - 1u));
        TEST_ASSERT(bytes_equal(out1, out2, ROM_SHA256_DIGEST_SIZE),
                    "identical inputs produced different MACs");

        rom_hmac_sha256(out2, key2, (uint32_t)(sizeof(key2) - 1u), data,
                        (uint32_t)(sizeof(data) - 1u));
        TEST_ASSERT(!bytes_equal(out1, out2, ROM_SHA256_DIGEST_SIZE),
                    "different key produced same MAC");

        rom_hmac_sha256(out2, key, (uint32_t)(sizeof(key) - 1u), data2,
                        (uint32_t)(sizeof(data2) - 1u));
        TEST_ASSERT(!bytes_equal(out1, out2, ROM_SHA256_DIGEST_SIZE),
                    "different data produced same MAC");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("rom_const_time_memcmp / rom_secure_memzero");
    {
        static const uint8_t a[16] = {0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
                                      0x88, 0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
        uint8_t b[16];
        int cleared = 1;

        for (uint32_t i = 0u; i < 16u; i++) b[i] = a[i];

        TEST_ASSERT(rom_const_time_memcmp(a, b, sizeof(a)) == 0,
                    "equal buffers reported as different");

        b[7] = (uint8_t)(b[7] ^ 0xFFu);
        TEST_ASSERT(rom_const_time_memcmp(a, b, sizeof(a)) == 1,
                    "differing buffers reported as equal");

        TEST_ASSERT(rom_pointers_are_equal_ct(a, a) == 1, "equal pointers not detected");
        TEST_ASSERT(rom_pointers_are_equal_ct(a, b) == 0, "different pointers reported equal");

        rom_secure_memzero(b, sizeof(b));
        for (uint32_t i = 0u; i < 16u; i++) {
            if (b[i] != 0u) {
                cleared = 0;
                break;
            }
        }
        TEST_ASSERT(cleared, "rom_secure_memzero did not clear buffer");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
