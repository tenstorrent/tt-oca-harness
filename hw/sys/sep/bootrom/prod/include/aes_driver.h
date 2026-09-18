/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// AES-128-CBC decryption driver for OROM.
//
// Drives the OpenTitan AES IP for payload decryption.
// Register interface ported from fw/sep/tests/sep_aes_basic_smoke_test.
// Matches the ROM AES-128-CBC decryption helper semantics.

#pragma once

#include <stdint.h>

// Initialize AES: release from SW reset.
// Returns 0 on success, non-zero on failure.
int aes_init(void);

// Decrypt data in-place using AES-128-CBC.
//
// Parameters:
//   data    - pointer to ciphertext (decrypted in-place), must be 16-byte aligned
//   len     - length in bytes (must be multiple of 16)
//   key     - 16 bytes AES-128 key
//   iv      - 16 bytes initialization vector
//
// Returns 0 on success, non-zero on failure.
// Decrypt data[0..len) in place with AES-CBC. key_bytes selects the key length:
// 16 (AES-128) or 32 (AES-256); anything else is rejected rather than defaulted.
// len must be non-zero and a multiple of 16. Returns 0 on success.
int aes_cbc_decrypt(uint8_t *data, uint32_t len, const uint8_t *key, uint32_t key_bytes,
                    const uint8_t *iv);

// Validate and strip PKCS#7 padding, writing the recovered length to out_len.
// Returns 0 when the padding is well formed, non-zero otherwise.
int aes_pkcs7_strip(const uint8_t *data, uint32_t len, uint32_t *out_len);
