/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// KBKDF-HMAC-SHA256 key derivation for OROM.
//
// Derives AES encryption keys from class_key + manifest KDF inputs.
// Implements the ROM KBKDF-HMAC-SHA256 helper.

#pragma once

#include <stdint.h>

// Derive a key using KBKDF in counter mode with HMAC-SHA256 as PRF.
//
// Parameters:
//   key      - input key material (e.g., class_key from fuse)
//   key_len  - length of key in bytes
//   info     - context/info string (16 bytes from manifest KDF input)
//   salt     - salt (16 bytes from manifest KDF input)
//   out      - output buffer for derived key
//   out_len  - desired output length in bytes (max 32)
//
// Returns 0 on success, non-zero on failure.
int kbkdf_hmac_sha256(const uint8_t *key, uint32_t key_len, const uint8_t *info,
                      const uint8_t *salt, uint8_t *out, uint32_t out_len);
