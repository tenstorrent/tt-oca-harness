/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// RSA-3072 signature verification for OROM.
//
// Uses OTBN coprocessor for modular exponentiation and verifies
// PKCS#1 v1.5 padding with SHA-256 digest.

#pragma once

#include <stdint.h>

// Verify an RSA-3072 signature over a SHA-256 digest.
//
// Parameters:
//   digest     - 32 bytes, SHA-256 digest of the TBS region (standard byte order)
//   signature  - 384 bytes, RSA-3072 signature (big-endian byte order)
//   modulus    - 384 bytes, RSA-3072 public key modulus (big-endian byte order)
//
// Returns 0 on success (signature valid), non-zero on failure.
int rsa_3072_verify(const uint8_t *digest, const uint8_t *signature, const uint8_t *modulus);
