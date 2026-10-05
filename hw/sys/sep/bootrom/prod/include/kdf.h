/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// KBKDF-HMAC-SHA256 key derivation for OROM.
//
// OCA payload-decryption key derivation (SP 800-108r1 CTR-HMAC-SHA-256).

#pragma once

#include <stdint.h>

// Derive the AES key for an encrypted OCA payload.
//
// secret     - the provisioned class secret (32 bytes for the CLASS_KEY bank)
// secret_len - its length in bytes
// kdf_input  - the manifest's 64-byte encryption_kdf_input, verbatim
// key_bits   - 128 for AES-128-CBC, 256 for AES-256-CBC; nothing else
// out_key    - receives key_bits/8 bytes
//
// Returns 0 on success. On failure out_key is wiped rather than left holding a
// partially derived key.
int oca_derive_payload_key(const uint8_t *secret, uint32_t secret_len, const uint8_t *kdf_input,
                           uint32_t key_bits, uint8_t *out_key);
