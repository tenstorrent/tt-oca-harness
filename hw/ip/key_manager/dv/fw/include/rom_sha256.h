/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_sha256.h
 * @brief Software SHA-256 for Key Manager ROM firmware.
 *
 * Based on Olivier Gay's FIPS 180-2 SHA-256 implementation, with added
 * length/overflow bounds checks and an `error` flag for fault resistance.
 */

#ifndef ROM_SHA256_H
#define ROM_SHA256_H

#include <stdint.h>

/** @brief SHA-256 digest length in bytes. */
#define ROM_SHA256_DIGEST_SIZE 32
/** @brief SHA-256 block length in bytes. */
#define ROM_SHA256_BLOCK_SIZE 64

/** @brief Incremental SHA-256 context. */
struct rom_sha256_ctx {
    uint32_t h[8];
    uint32_t tot_len;
    uint32_t len;
    uint8_t block[2 * ROM_SHA256_BLOCK_SIZE];
    uint8_t buf[ROM_SHA256_DIGEST_SIZE]; /**< Holds the final digest. */
    int error;                           /**< Non-zero if overflow/other error occurred. */
};

/**
 * @brief Initialize a SHA-256 context.
 *
 * @param ctx Context to initialize.
 */
void rom_sha256_init(struct rom_sha256_ctx *ctx);

/**
 * @brief Initialize a SHA-256 context with one complete input block.
 *
 * This specialized initializer is used by the HMAC-SHA256 implementation.
 *
 * @param ctx  Context to initialize.
 * @param data Exactly ROM_SHA256_BLOCK_SIZE bytes of input.
 */
void rom_sha256_init_one_block(struct rom_sha256_ctx *ctx, const uint8_t *data);

/**
 * @brief Absorb @p len bytes of @p data into the SHA-256 context.
 *
 * On detecting a corrupted length or a `tot_len` overflow, the context's
 * `error` flag is set and the update is dropped; the subsequent
 * rom_sha256_final() then returns NULL.
 *
 * @param ctx  Context.
 * @param data Input bytes (may be NULL only when @p len is 0).
 * @param len  Number of input bytes.
 */
void rom_sha256_update(struct rom_sha256_ctx *ctx, const uint8_t *data, uint32_t len);

/**
 * @brief Finalize the digest.
 *
 * @param ctx Context.
 * @return Pointer to the 32-byte digest stored inside @p ctx, or NULL if an
 *         error was flagged during rom_sha256_update().
 */
uint8_t *rom_sha256_final(struct rom_sha256_ctx *ctx);

#endif /* ROM_SHA256_H */
