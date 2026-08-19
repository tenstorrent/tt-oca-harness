/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Manifest crypto validation for OROM (C13.10).
//
// Orchestrates all cryptographic checks on a loaded manifest:
//   (a) BL1/BL2 version rollback check (fuse thermometer encoding)
//   (b) Public key revocation check (CHIPLET_PUBK_REVOKE fuse)
//   (c) RSA-3072 signature verification (OTBN modexp + PKCS#1 v1.5)
//   (d) Payload hash verification (SHA-256)
//   (e) Payload decryption (AES-128-CBC with KBKDF-HMAC-SHA256)
//
// Reference: manifest crypto validation flow in this ROM.

#pragma once

#include <stdint.h>
#include "manifest.h"

// Perform crypto validation on a manifest already loaded in SRAM.
// Includes: version check, key revocation, signature verify,
//           decrypt (if encrypted).
// Returns MANIFEST_OK (0) on success, MANIFEST_ERR_* on failure.
uint32_t manifest_crypto_validate(const manifest_t *m, uint32_t lc_state);

// Verify payload hash (SHA-256).
// Called regardless of secure_boot state.
// Must be called after decrypt_payload() if payload is encrypted.
// Returns MANIFEST_OK (0) on success, MANIFEST_ERR_* on failure.
uint32_t verify_payload_hash(const manifest_t *m);
