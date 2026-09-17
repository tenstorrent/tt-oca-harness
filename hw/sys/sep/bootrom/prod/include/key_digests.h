/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// ROM-embedded public key digests for secure boot.
//
// Contains SHA-256 digests of allowed RSA-3072 public keys (moduli).
// The ROM verifies a manifest's public key by hashing it and comparing
// against these compiled-in digests (for ROM key slots) or against
// fuse-stored digests (for fuse key slots).
//
// Only the key digest is stored here;
// OTBN handles Montgomery precomputation internally, so we only store
// the key digest.
//
// The table is generated at build time by tools/generate_key_digests.py, into the
// build directory rather than the source tree, so the anchors cannot drift from the
// keys they were taken from. Every entry is SHA-256 over the PUBLIC modulus; the
// build type selects only which file form that modulus is read out of -- the private
// test keys in tests/signing_keys/ for debug, public keys from a directory that ships
// empty for release. No private key material reaches the digest either way. See the
// Makefile's SEP_ROM_KEYS_DIR.

#pragma once

#include <stdint.h>
#include <stdbool.h>

// The count is the number of ROM key slots the digest table pins; the size is
// the RSA-3072 modulus that gets hashed.
#ifndef PUBK_SEL_NUM_ROM_KEYS
#define PUBK_SEL_NUM_ROM_KEYS 6
#endif
#ifndef RSA_3072_KEY_SZ_BYTES
#define RSA_3072_KEY_SZ_BYTES 384
#endif

#ifndef SHA256_DIGEST_SIZE_BYTES
#define SHA256_DIGEST_SIZE_BYTES 32
#endif

// Per-key information stored in ROM.
typedef struct {
    const uint8_t *digest; // SHA-256 of the RSA-3072 modulus (32 bytes), or NULL
} public_key_info_t;

// Number of ROM key slots.
#define NUM_PUBLIC_KEY_DIGESTS PUBK_SEL_NUM_ROM_KEYS

// ROM key digest table.
// Index 0..5 are ROM key slots 0..5, matching public_key_select_classic
// bits [7:0] and the same bit numbering in CHIPLET_PUBK_REVOKE. The slot
// number is the whole identity: the ROM draws no trust distinction between
// slots when resolving them.
// Entries with digest == NULL are considered empty/unused.
extern public_key_info_t public_key_digests[NUM_PUBLIC_KEY_DIGESTS];
