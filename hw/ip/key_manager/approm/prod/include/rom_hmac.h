/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_hmac.h
 * @brief Software HMAC-SHA256 for Key Manager ROM firmware.
 */

#ifndef ROM_HMAC_H
#define ROM_HMAC_H

#include <stdint.h>

#include "rom_sha256.h"

/**
 * @brief Maximum message size supported by the HMAC implementation.
 *
 * The SHA-256 implementation stores the final bit length in 32 bits. Reserve
 * one SHA-256 block for HMAC's inner key pad.
 */
#define ROM_HMAC_MAX_MESSAGE_BYTES ((UINT32_MAX >> 3) - (uint32_t)ROM_SHA256_BLOCK_SIZE)

/**
 * @brief Compute HMAC-SHA256.
 *
 * Writes the 32-byte MAC to @p output. The implementation does not support
 * keys longer than the SHA-256 block size (64 bytes); if @p key_len exceeds
 * it or @p message_len exceeds ROM_HMAC_MAX_MESSAGE_BYTES, @p output is
 * zeroed and no MAC is produced (fail-safe).
 *
 * @param output       Destination for the 32-byte MAC; must not be NULL.
 * @param key          HMAC key. May be NULL only when @p key_len is zero.
 * @param key_len      Key length in bytes (must be <= ROM_SHA256_BLOCK_SIZE).
 * @param message      Message to authenticate (may be NULL only when length is 0).
 * @param message_len  Message length in bytes (must be <=
 *                     ROM_HMAC_MAX_MESSAGE_BYTES).
 * @return 0 on success, or -1 if arguments are invalid or SHA-256 fails.
 */
int rom_hmac_sha256(uint8_t *output, const uint8_t *key, uint32_t key_len, const uint8_t *message,
                    uint32_t message_len);

#endif /* ROM_HMAC_H */
