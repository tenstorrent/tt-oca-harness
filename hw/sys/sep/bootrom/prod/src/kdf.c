/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// KBKDF-HMAC-SHA256 key derivation for OROM.
//
// Implements NIST SP 800-108 KBKDF in counter mode with HMAC-SHA256 as PRF.
// This is the ROM KBKDF-HMAC-SHA256 flow.
//
// KDF input format (single iteration, counter=1):
//   HMAC-SHA256(key, counter || info || 0x00 || salt || output_length_bits)
//
// Where:
//   counter = 4-byte big-endian (0x00000001)
//   info    = 16 bytes from manifest KDF input (first half)
//   0x00    = 1-byte separator
//   salt    = 16 bytes from manifest KDF input (second half)
//   output_length_bits = 4-byte big-endian (out_len * 8)

#include "kdf.h"

#include <stdint.h>

#include "hmac_sha256.h"
#include "errors.h"

// Maximum KDF argument size.
#define MAX_KDF_ARG_BYTES 16

int kbkdf_hmac_sha256(const uint8_t *key, uint32_t key_len, const uint8_t *info,
                      const uint8_t *salt, uint8_t *out, uint32_t out_len) {
    if (out_len > 32u) return -1; // Max one HMAC block.

    // Build the PRF input message:
    //   [4: counter=1] [16: info] [1: 0x00] [16: salt] [4: L_bits]
    // Total: 41 bytes.
    uint8_t msg[41];
    uint32_t idx = 0;

    // Counter = 1 (big-endian).
    msg[idx++] = 0x00;
    msg[idx++] = 0x00;
    msg[idx++] = 0x00;
    msg[idx++] = 0x01;

    // Info (16 bytes).
    for (uint32_t i = 0; i < MAX_KDF_ARG_BYTES; ++i) {
        msg[idx++] = info[i];
    }

    // Separator.
    msg[idx++] = 0x00;

    // Salt (16 bytes).
    for (uint32_t i = 0; i < MAX_KDF_ARG_BYTES; ++i) {
        msg[idx++] = salt[i];
    }

    // Output length in bits (big-endian).
    uint32_t L_bits = out_len * 8u;
    msg[idx++] = (uint8_t)(L_bits >> 24);
    msg[idx++] = (uint8_t)(L_bits >> 16);
    msg[idx++] = (uint8_t)(L_bits >> 8);
    msg[idx++] = (uint8_t)(L_bits);

    // Compute HMAC-SHA256(key, msg).
    uint8_t hmac_out[32];
    int rc = hmac_sha256(key, key_len, msg, idx, hmac_out);
    if (rc != 0) {
        simputs("KDF_HMAC_FAIL\n");
        return rc;
    }

    // Copy the requested number of output bytes.
    for (uint32_t i = 0; i < out_len; ++i) {
        out[i] = hmac_out[i];
    }

    // Wipe intermediate key material.
    for (uint32_t i = 0; i < 32; ++i) {
        ((volatile uint8_t *)hmac_out)[i] = 0;
    }
    for (uint32_t i = 0; i < sizeof(msg); ++i) {
        ((volatile uint8_t *)msg)[i] = 0;
    }

    return 0;
}
