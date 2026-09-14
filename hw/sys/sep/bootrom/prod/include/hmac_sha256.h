/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// HMAC SHA-256 hardware driver for OROM.
//
// Drives the OpenTitan HMAC IP (at HMAC_REG_MAP_BASE_ADDR = 0x10911000)
// in SHA-256-only mode (hmac_en=0, sha_en=1) or HMAC mode (hmac_en=1).
//
// Programming model follows the OpenTitan HMAC Programmer's Guide and
// the proven sequence from fw/sep/tests/hmac_test/hmac_test.c.
//
// API matches the ROM SHA-256 helper semantics.

#pragma once

#include <stdint.h>

// Compute SHA-256 of data[0..len-1].
// Writes 32 bytes to digest[].
// Returns 0 on success, non-zero on timeout/error.
int sha256(const uint8_t *data, uint32_t len, uint8_t *digest);

// Compute HMAC-SHA256(key, data).
// key: HMAC key (up to 32 bytes; zero-padded to 256 bits internally by IP).
// key_len: key length in bytes (max 32).
// data/data_len: message to authenticate.
// digest: output buffer (32 bytes).
// Returns 0 on success, non-zero on timeout/error.
int hmac_sha256(const uint8_t *key, uint32_t key_len, const uint8_t *data, uint32_t data_len,
                uint8_t *digest);
