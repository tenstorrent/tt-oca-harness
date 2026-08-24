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
int aes128cbc_decrypt(uint8_t *data, uint32_t len, const uint8_t *key, const uint8_t *iv);
