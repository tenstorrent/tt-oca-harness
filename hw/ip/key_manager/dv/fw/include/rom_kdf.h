/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kdf.h
 * @brief SP 800-108r1 counter-mode KDF for Key Manager ROM firmware.
 */

#ifndef ROM_KDF_H
#define ROM_KDF_H

#include <stddef.h>
#include <stdint.h>

/** @brief Size of the fixed KDF input header in bytes. */
#define KM_KDF_HDR_BYTES 32u
/** @brief Size of the KDF domain-separation label in bytes. */
#define KM_KDF_LABEL_BYTES 32u
/** @brief Size of the caller-provided KDF context in bytes. */
#define KM_KDF_CONTEXT_BYTES 64u
/** @brief Size of the optional KDF entropy field in bytes. */
#define KM_KDF_ENTROPY_BYTES 64u
/** @brief Total fixed KDF input size: three SHA-256 blocks. */
#define KM_KDF_INPUT_BYTES 192u
/** @brief Maximum supported KDF output size in bits. */
#define KM_KDF_OUT_MAX_BITS 8192u

/**
 * @brief Fixed input data mixed into every KDF invocation.
 *
 * The structure is mixed into the HMAC input verbatim. Multi-byte structure
 * fields therefore use their in-memory byte representation. Only the KDF
 * counter and output length that surround this structure are big-endian.
 */
typedef struct {
    /* 32-byte header. */
    uint16_t version;
    uint8_t out_class;
    uint8_t out_type;
    uint8_t out_owner;
    uint8_t out_domain;
    uint16_t flags;
    uint16_t purpose;
    uint16_t out_bits;
    uint32_t caps;
    uint32_t device_state;
    uint8_t rsvd[12];

    /* 160-byte body. */
    uint8_t label[KM_KDF_LABEL_BYTES];
    uint8_t context[KM_KDF_CONTEXT_BYTES];
    uint8_t entropy[KM_KDF_ENTROPY_BYTES];
} km_kdf_input_t;

_Static_assert(sizeof(km_kdf_input_t) == KM_KDF_INPUT_BYTES, "kdf input ABI");
_Static_assert(offsetof(km_kdf_input_t, version) == 0u, "kdf version offset");
_Static_assert(offsetof(km_kdf_input_t, out_class) == 2u, "kdf class offset");
_Static_assert(offsetof(km_kdf_input_t, out_type) == 3u, "kdf type offset");
_Static_assert(offsetof(km_kdf_input_t, out_owner) == 4u, "kdf owner offset");
_Static_assert(offsetof(km_kdf_input_t, out_domain) == 5u, "kdf domain offset");
_Static_assert(offsetof(km_kdf_input_t, flags) == 6u, "kdf flags offset");
_Static_assert(offsetof(km_kdf_input_t, purpose) == 8u, "kdf purpose offset");
_Static_assert(offsetof(km_kdf_input_t, out_bits) == 10u, "kdf out_bits offset");
_Static_assert(offsetof(km_kdf_input_t, caps) == 12u, "kdf caps offset");
_Static_assert(offsetof(km_kdf_input_t, device_state) == 16u, "kdf device_state offset");
_Static_assert(offsetof(km_kdf_input_t, rsvd) == 20u, "kdf reserved offset");
_Static_assert(offsetof(km_kdf_input_t, label) == KM_KDF_HDR_BYTES, "kdf label offset");
_Static_assert(offsetof(km_kdf_input_t, context) == KM_KDF_HDR_BYTES + KM_KDF_LABEL_BYTES,
               "kdf context offset");
_Static_assert(offsetof(km_kdf_input_t, entropy) ==
                   KM_KDF_HDR_BYTES + KM_KDF_LABEL_BYTES + KM_KDF_CONTEXT_BYTES,
               "kdf entropy offset");

/**
 * @brief Derive key material using SP 800-108r1 counter mode.
 *
 * Computes:
 *
 * `K(i) = HMAC-SHA-256(key, BE16(i) || input[192] || BE16(out_bits))`
 *
 * and returns the leftmost @p out_bits of `K(1) || K(2) || ...`. Keys longer
 * than the SHA-256 block size are first hashed according to RFC 2104.
 *
 * @param key       HMAC key. May be NULL only when @p key_len is zero.
 * @param key_len   Key length in bytes.
 * @param input     Fixed 192-byte KDF input.
 * @param output    Destination for `ceil(out_bits / 8)` bytes.
 * @param out_bits  Requested output size, from 1 through KM_KDF_OUT_MAX_BITS.
 * @return 0 on success, or -1 on invalid arguments or a cryptographic failure.
 *         On a cryptographic failure, the requested output region is zeroed.
 */
int rom_kdf_800_108(const uint8_t *key, uint32_t key_len, const km_kdf_input_t *input,
                    uint8_t *output, uint16_t out_bits);

/**
 * @brief Run the embedded KDF known-answer power-on self-test.
 *
 * @return 1 when the derived output matches the embedded expected value, or
 *         0 on a KDF failure or mismatch.
 */
int rom_kdf_selftest(void);

#endif /* ROM_KDF_H */
