/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kdf.c
 * @brief SP 800-108r1 counter-mode KDF for Key Manager ROM firmware.
 */

#include <stddef.h>
#include <stdint.h>

#include "rom_hmac.h"
#include "rom_kdf.h"
#include "rom_secutil.h"
#include "rom_sha256.h"

/* Provided by rom_memcpy.c (libc-name alias). */
void *memcpy(void *dest, const void *src, size_t n);

/*
 * KDF scratch lives in BSS rather than on the stack. The KM firmware is
 * single-threaded, so one shared workspace is sufficient. All fields are
 * scrubbed together before rom_kdf_800_108() returns.
 */
static struct {
    uint8_t message[2u + KM_KDF_INPUT_BYTES + 2u];
    uint8_t block[ROM_SHA256_DIGEST_SIZE];
    struct rom_sha256_ctx key_ctx;
} g_kdf;

/**
 * @brief Normalize an HMAC key according to RFC 2104.
 *
 * HMAC uses keys of at most one hash block directly. Longer keys are reduced
 * to one SHA-256 digest before use.
 */
static int rom_kdf_prepare_key(const uint8_t *key, uint32_t key_len, const uint8_t **prf_key,
                               uint32_t *prf_key_len) {
    uint8_t *digest;

    if (key_len <= (uint32_t)ROM_SHA256_BLOCK_SIZE) {
        *prf_key = key;
        *prf_key_len = key_len;
        return 0;
    }

    rom_sha256_init(&g_kdf.key_ctx);
    rom_sha256_update(&g_kdf.key_ctx, key, key_len);
    digest = rom_sha256_final(&g_kdf.key_ctx);
    if (digest == NULL) return -1;

    *prf_key = digest;
    *prf_key_len = (uint32_t)ROM_SHA256_DIGEST_SIZE;
    return 0;
}

int rom_kdf_800_108(const uint8_t *key, uint32_t key_len, const km_kdf_input_t *input,
                    uint8_t *output, uint16_t out_bits) {
    const uint8_t *prf_key;
    uint32_t prf_key_len;
    uint32_t out_len;
    uint16_t iteration_count;
    int ret = -1;

    if (((key == NULL) && (key_len != 0u)) || (input == NULL) || (output == NULL) ||
        (out_bits == 0u) || (out_bits > (uint16_t)KM_KDF_OUT_MAX_BITS)) {
        rom_secure_memzero(&g_kdf, sizeof(g_kdf));
        return -1;
    }

    out_len = ((uint32_t)out_bits + 7u) / 8u;
    iteration_count = (uint16_t)((out_len + (uint32_t)ROM_SHA256_DIGEST_SIZE - 1u) /
                                 (uint32_t)ROM_SHA256_DIGEST_SIZE);

    if (rom_kdf_prepare_key(key, key_len, &prf_key, &prf_key_len) != 0) {
        rom_secure_memzero(output, out_len);
        goto cleanup;
    }

    memcpy(g_kdf.message + 2u, input, KM_KDF_INPUT_BYTES);
    g_kdf.message[2u + KM_KDF_INPUT_BYTES] = (uint8_t)(out_bits >> 8);
    g_kdf.message[2u + KM_KDF_INPUT_BYTES + 1u] = (uint8_t)(out_bits & 0xffu);

    for (uint16_t i = 1u; i <= iteration_count; i++) {
        uint32_t offset = (uint32_t)(i - 1u) * (uint32_t)ROM_SHA256_DIGEST_SIZE;
        uint32_t remaining = out_len - offset;
        uint32_t take = remaining > (uint32_t)ROM_SHA256_DIGEST_SIZE
                            ? (uint32_t)ROM_SHA256_DIGEST_SIZE
                            : remaining;

        g_kdf.message[0] = (uint8_t)(i >> 8);
        g_kdf.message[1] = (uint8_t)(i & 0xffu);

        if (rom_hmac_sha256(g_kdf.block, prf_key, prf_key_len, g_kdf.message,
                            (uint32_t)sizeof(g_kdf.message)) != 0) {
            rom_secure_memzero(output, out_len);
            goto cleanup;
        }

        memcpy(output + offset, g_kdf.block, take);
    }

    ret = 0;

cleanup:
    rom_secure_memzero(&g_kdf, sizeof(g_kdf));
    return ret;
}

/* Fixed two-iteration known-answer vector: 32-byte key, 512-bit output. */
static const uint8_t KDF_POST_KEY[32] = {
    0x42, 0x7d, 0x32, 0xbb, 0x8f, 0xd7, 0x26, 0x69, 0x6b, 0x5f, 0x92, 0x65, 0xf0, 0x25, 0x2f, 0x37,
    0x0d, 0xbc, 0xab, 0x1a, 0x35, 0x39, 0xa2, 0x74, 0x7f, 0x8d, 0x34, 0x29, 0x5e, 0xe1, 0x24, 0x78};

typedef union {
    km_kdf_input_t input;
    uint8_t bytes[KM_KDF_INPUT_BYTES];
} kdf_post_input_t;

static const kdf_post_input_t KDF_POST_INPUT = {
    .bytes = {0x75, 0x2b, 0x79, 0x11, 0xa9, 0xd5, 0x4d, 0xe9, 0x1d, 0xc3, 0x28, 0x48, 0xff, 0xb1,
              0xbf, 0x46, 0x46, 0xaf, 0x45, 0x70, 0xdb, 0x8b, 0xd4, 0xec, 0x78, 0x98, 0xc9, 0x32,
              0x83, 0x4f, 0x4c, 0x19, 0x15, 0x76, 0x3b, 0xb5, 0x7e, 0x99, 0xea, 0x21, 0x18, 0xeb,
              0x5c, 0x87, 0xad, 0xe6, 0x50, 0xea, 0x26, 0x18, 0x5a, 0x23, 0x23, 0x0d, 0xbf, 0x27,
              0xc4, 0x1d, 0x74, 0xc2, 0x42, 0x25, 0x1b, 0x90, 0x0d, 0xd6, 0x87, 0x54, 0xb4, 0x35,
              0xb1, 0x42, 0x38, 0x0a, 0xed, 0xc1, 0x37, 0x05, 0x5c, 0x7b, 0x35, 0x9f, 0x61, 0x50,
              0x25, 0x67, 0xd0, 0xb2, 0xe5, 0x6d, 0x98, 0x93, 0xcc, 0x16, 0x5e, 0x42, 0xe9, 0x00,
              0x52, 0xd6, 0x3f, 0x7e, 0x8b, 0x19, 0xb6, 0xcd, 0x12, 0x24, 0xc1, 0x18, 0xe8, 0xd7,
              0x8c, 0x8f, 0xf4, 0x74, 0x85, 0xb7, 0x4b, 0xd7, 0x9b, 0xaf, 0x13, 0xb1, 0x60, 0x6a,
              0xe7, 0x49, 0x18, 0xa5, 0xd8, 0xa8, 0x00, 0x06, 0x61, 0x50, 0x3f, 0x39, 0x23, 0xa2,
              0x75, 0xd1, 0xd7, 0xec, 0xcd, 0x2a, 0x13, 0x87, 0x2f, 0xd1, 0xf8, 0x55, 0x05, 0x1b,
              0xa0, 0xc9, 0x91, 0xae, 0xab, 0xc0, 0x38, 0xdc, 0x10, 0xb3, 0xf4, 0xc1, 0x33, 0xbd,
              0x6b, 0x1e, 0xe2, 0xbd, 0x39, 0x7c, 0x71, 0x4d, 0xe4, 0x59, 0xe0, 0xac, 0x28, 0x4d,
              0x59, 0x97, 0x83, 0xa3, 0xf1, 0xb3, 0x1d, 0x42, 0xde, 0x31}};

#define KDF_POST_OUT_BITS 512u
static const uint8_t KDF_POST_EXPECT[KDF_POST_OUT_BITS / 8u] = {
    0xc7, 0xa1, 0x82, 0x94, 0xe1, 0x1a, 0x50, 0x43, 0x54, 0x29, 0xa3, 0xa5, 0x47, 0xd9, 0x53, 0x82,
    0xf9, 0xf1, 0x4e, 0xb5, 0x61, 0x54, 0x40, 0x29, 0xbe, 0x72, 0x22, 0x5a, 0x3f, 0x53, 0x42, 0xe1,
    0xd0, 0xe3, 0x1b, 0xc9, 0xc7, 0x7e, 0x40, 0x12, 0xeb, 0xe7, 0x4c, 0x1a, 0x43, 0x82, 0x79, 0x61,
    0x37, 0x97, 0x69, 0x61, 0xa9, 0xc0, 0xcc, 0xcb, 0x35, 0x9f, 0xc4, 0x02, 0xdd, 0xf5, 0x51, 0x5c};

int rom_kdf_selftest(void) {
    uint8_t output[KDF_POST_OUT_BITS / 8u];
    int passed;

    passed = rom_kdf_800_108(KDF_POST_KEY, (uint32_t)sizeof(KDF_POST_KEY), &KDF_POST_INPUT.input,
                             output, (uint16_t)KDF_POST_OUT_BITS) == 0 &&
             rom_const_time_memcmp(output, KDF_POST_EXPECT, sizeof(output)) == 0;

    rom_secure_memzero(output, sizeof(output));
    return passed;
}
