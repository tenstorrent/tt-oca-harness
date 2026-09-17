/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// KBKDF-HMAC-SHA256 key derivation for OROM.
//
// SP 800-108r1 counter-mode KBKDF with HMAC-SHA-256 as the PRF, reproducing the
// OCAH Key Manager PREPARE_BL_DECRYPT_KEY flow:
//
//   block = header(32) || "KM_CLASS_BL"(32) || kdf_input(64) || entropy(64)
//   key   = HMAC-SHA256(secret, be16(i) || block || be16(L))[0 : L/8]
//
// for i = 1,2,... with L = key_bits (128 for AES-128-CBC, 256 for AES-256-CBC).
//
// This code implements a soft version of the KDF function used in the OCAH Key
// Manager. The OCA manifest carries a 64-byte kdf_input and wraps it in the Key
// Manager's defined 192-byte expanded block. Reference implementation:
// validators/oca/test/openssl_crypto.c derive_payload_key(); producer side
// src/oca/encryption.py; known-answer tests tests/test_oca_kdf_kat.py.
//
// One HMAC iteration covers both ciphers -- HMAC-SHA-256 emits 32 bytes and the
// largest key wanted is 32 -- so the counter loop collapses to i=1. The loop is
// still written as a loop because the construction is defined that way and a
// future 384-bit class key would otherwise silently truncate.

// Note that the output for a 128-bit key request is not just a truncation of
// a 256-bit key request. The requested length is part of the KDF input data
// and thus forces the output values of the HMAC function to be totally different

#include "kdf.h"

#include <stddef.h>
#include <stdint.h>

#include "errors.h"
#include "hmac_sha256.h"

// Expanded KDF input block: 32-byte header, 32-byte label, 64-byte context,
// 64-byte entropy.
#define KDF_BLOCK_BYTES 192u
#define KDF_LABEL_OFFSET 32u
#define KDF_CONTEXT_OFFSET 64u
#define KDF_CONTEXT_BYTES 64u

// PRF message: be16(counter) || block || be16(L_bits).
#define KDF_MSG_BYTES (2u + KDF_BLOCK_BYTES + 2u)

static void wipe(uint8_t *p, uint32_t len) {
    for (uint32_t i = 0; i < len; ++i) {
        ((volatile uint8_t *)p)[i] = 0u;
    }
}

int oca_derive_payload_key(const uint8_t *secret, uint32_t secret_len, const uint8_t *kdf_input,
                           uint32_t key_bits, uint8_t *out_key) {
    if (secret == NULL || kdf_input == NULL || out_key == NULL) {
        return -1;
    }
    if (key_bits != 128u && key_bits != 256u) {
        return -1;
    }

    uint8_t msg[KDF_MSG_BYTES];
    for (uint32_t i = 0; i < KDF_MSG_BYTES; ++i) {
        msg[i] = 0u;
    }

    uint8_t *block = msg + 2u;

    // 32-byte header, little-endian km_kdf_input_t fields. Every value here is
    // fixed by the Key Manager's BL-decrypt flow except out_bits, which is the
    // only field that varies with the cipher.
    block[0] = 0x01u;
    block[1] = 0x00u; // version = 0x0001
    block[2] = 0x01u; // out_class  = SYMMETRIC
    block[3] = 0x00u; // out_type   = SYM_RAW
    block[4] = 0x00u; // out_owner  = NONE
    block[5] = 0x01u; // out_domain = SW
    block[6] = 0x18u;
    block[7] = 0x00u; // flags = ROM_CREATED|ROM_LINEAGE
    block[8] = 0x00u;
    block[9] = 0x00u;                        // purpose = 0
    block[10] = (uint8_t)(key_bits & 0xFFu); // out_bits (LE)
    block[11] = (uint8_t)((key_bits >> 8) & 0xFFu);
    block[12] = 0x01u; // caps = SYM_AES (LE u32)
    // device_state (16..19) and rsvd (20..31) stay zero.

    // Label: "KM_CLASS_BL", NUL-padded to 32 bytes.
    static const char label[] = "KM_CLASS_BL";
    for (uint32_t i = 0; i < sizeof(label) - 1u; ++i) {
        block[KDF_LABEL_OFFSET + i] = (uint8_t)label[i];
    }

    // Context: the manifest's 64-byte kdf_input, verbatim.
    for (uint32_t i = 0; i < KDF_CONTEXT_BYTES; ++i) {
        block[KDF_CONTEXT_OFFSET + i] = kdf_input[i];
    }
    // Entropy (128..191) stays zero.

    // L, big-endian, in the two bytes after the block.
    msg[2u + KDF_BLOCK_BYTES] = (uint8_t)((key_bits >> 8) & 0xFFu);
    msg[2u + KDF_BLOCK_BYTES + 1u] = (uint8_t)(key_bits & 0xFFu);

    const uint32_t out_len = key_bits / 8u;
    uint32_t done = 0u;
    int rc = 0;

    for (uint32_t i = 1u; done < out_len; ++i) {
        // Counter, big-endian, in the two bytes before the block.
        msg[0] = (uint8_t)((i >> 8) & 0xFFu);
        msg[1] = (uint8_t)(i & 0xFFu);

        uint8_t mac[32];
        rc = hmac_sha256(secret, secret_len, msg, KDF_MSG_BYTES, mac);
        if (rc != 0) {
            simputs("KDF_HMAC_FAIL\n");
            wipe(mac, sizeof mac);
            break;
        }
        uint32_t take = (out_len - done > 32u) ? 32u : (out_len - done);
        for (uint32_t j = 0; j < take; ++j) {
            out_key[done + j] = mac[j];
        }
        done += take;
        wipe(mac, sizeof mac);
    }

    // The block carries the KDF context, not the secret, but it is still
    // material an attacker would like off the stack.
    wipe(msg, sizeof msg);

    if (rc != 0) {
        wipe(out_key, out_len);
        return rc;
    }
    return 0;
}
