/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP platform binding for the OCA boot-manifest validation library.
//
// Each callback is a thin adapter over a driver the ROM already had, so the
// format change does not bring new hardware access with it: hashing is the
// OpenTitan HMAC core, signature verification is the OTBN RSA-3072 app, and the
// rest are eFuse shadow-register reads.
//
// Two conventions from INTEGRATION.md that are easy to get wrong and are the
// reason this file is deliberately literal:
//
//   * The boolean reporters return oca_secure_bool_t, not a C bool. `return 1`
//     reads as "secure boot enforced" because 1 is neither of the two sentinels
//     and the library treats anything that is not OCA_SECURE_FALSE as not-false.
//   * OCA_HW_UNAVAILABLE is a hard failure, not "this constraint does not apply".
//     The library only calls a fuse read when the manifest's selector bits
//     actually constrain that field, so there is no such thing as a read it did
//     not want the answer to.

#include "oca_platform.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bl0_state.h"
#include "aes_driver.h"
#include "hmac_sha256.h"
#include "kdf.h"
#include "lifecycle.h"
#include "rom_mmio.h"
#include "errors.h"
#include "sep_helpers.h"
#include "status_values.h"
#include "key_digests.h"
#include "rom_virt_console.h"
#include "rsa_verify.h"
#include "sep_addr.h"

// Entropy chain bring-up is behind SEP_ENTROPY_BRINGUP while it is being brought
// up; with the flag off the crypto blocks still rely on the DV
// +sep_crypto_edn_force shortcut, which is what this replaces. Wrapped in a
// macro so the two crypto gates below read the same either way and the
// conditional lives in exactly one place.
#if SEP_ENTROPY_BRINGUP
#include "sep_entropy.h"
#define ENTROPY_PREREQ() sep_entropy_init()
#else
#define ENTROPY_PREREQ() ((void)0)
#endif

// RAW RSA-3072 public key: 384-byte big-endian modulus followed by a 4-byte
// big-endian exponent (openssl_crypto.c rsa_key_from_raw is the reference).
#define OCA_RSA3072_MODULUS_BYTES 384u
#define OCA_RSA3072_EXPONENT_BYTES 4u
#define OCA_RSA3072_PUBKEY_BYTES (OCA_RSA3072_MODULUS_BYTES + OCA_RSA3072_EXPONENT_BYTES)
#define OCA_RSA3072_SIGNATURE_BYTES 384u

// The only exponent the OTBN app implements: it is built as
// MODE_RSA_3072_MODEXP_F4, so e is wired to F4 and never read from the key.
// A key carrying any other exponent would otherwise be verified against 65537
// regardless of what it says, which is a silent wrong-key accept.
#define OCA_RSA_EXPONENT_F4 0x00010001u

// Identity banks are 32 bytes each (base-address deltas in sep_addr.h), which is
// exactly the width get_identity_bytes must fill.
#define OCA_IDENTITY_BYTES 32u

// Read a little-endian byte image out of a 32-bit-word eFuse shadow bank:
// word[0] holds bits[31:0], and byte 0 is that word's LSB.
static void fuse_read_bytes(uint32_t base, uint8_t *out, uint32_t len) {
    for (uint32_t i = 0; i < len; i += 4u) {
        uint32_t val = mmio_read32(base + i);
        out[i] = (uint8_t)(val);
        out[i + 1u] = (uint8_t)(val >> 8);
        out[i + 2u] = (uint8_t)(val >> 16);
        out[i + 3u] = (uint8_t)(val >> 24);
    }
}

static uint32_t be32_load(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

// -- hashing ----------------------------------------------------------------

static oca_result_t plat_sha256(const uint8_t *msg, size_t msg_len, uint8_t out_digest[32]) {
    if (msg == NULL || out_digest == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }

    // plat_sha256() deliberately does NOT confirm entropy: the HMAC core needs
    // no EDN reseed (the KDF runs on it with the chain absent), and this
    // callback runs on every boot including unsigned ones, so requiring entropy
    // there would make a boot that needs no crypto depend on the entropy source.

    // The HMAC core takes a uint32_t length. A manifest body is 4 KiB and a
    // payload is bounded by SEP SRAM (256 KiB), so this cannot legitimately
    // overflow -- but the cast is where it would, so check rather than assume.
    if (msg_len > (size_t)UINT32_MAX) {
        return OCA_FAIL_INVALID_ARG;
    }
    if (sha256(msg, (uint32_t)msg_len, out_digest) != 0) {
        // A wedged or timed-out HMAC core is not a hash mismatch: reporting it
        // as one would blame the image for a hardware fault.
        return OCA_FAIL_CALLBACK_UNAVAILABLE;
    }
    return OCA_OK;
}

// -- signature verification -------------------------------------------------

static oca_result_t plat_verify_signature(const oca_crypto_blob_t *signature,
                                          const oca_crypto_blob_t *public_key,
                                          const uint8_t *signed_region, size_t signed_region_len) {
    uint8_t digest[32];

    if (signature == NULL || public_key == NULL || signed_region == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }

    // Entropy is confirmed on entry to each callback that drives an
    // entropy-dependent engine. It is a prerequisite of the OTBN engine,
    // not an initialization step inside it, so it is established early in the
    // signature verification call rather than rediscovered by the driver.
    // Does not return on failure, but does fail the secure boot process.
    ENTROPY_PREREQ();

    // RSA-3072 PKCS#1 v1.5 / SHA-256 only. ECDSA P-256 (0x05) is a valid OCA
    // primitive the ROM has no verifier for, and the PQC variants carry no
    // native signature the library can check either. Refusing here is the clean
    // "unsupported" the format expects -- never a pass.
    if (signature->primitive_type != OCA_PRIMITIVE_RSA_3072_PKCS1V15_SHA256 ||
        public_key->primitive_type != OCA_PRIMITIVE_RSA_3072_PKCS1V15_SHA256) {
        return OCA_FAIL_SIGNATURE;
    }

    // RAW only: DER would mean an ASN.1 parser inside a 64 KiB ROM, and the
    // producer configs pin raw encoding for exactly that reason.
    if (signature->encoding != OCA_ENCODING_RAW || public_key->encoding != OCA_ENCODING_RAW) {
        return OCA_FAIL_SIGNATURE;
    }

    // field_length is the manifest field width, not the encoded length, so this
    // is a "does the field even hold the primitive" check.
    if (signature->field_length < OCA_RSA3072_SIGNATURE_BYTES ||
        public_key->field_length < OCA_RSA3072_PUBKEY_BYTES) {
        return OCA_FAIL_SIGNATURE;
    }

    if (be32_load(public_key->bytes + OCA_RSA3072_MODULUS_BYTES) != OCA_RSA_EXPONENT_F4) {
        return OCA_FAIL_SIGNATURE;
    }

    if (plat_sha256(signed_region, signed_region_len, digest) != OCA_OK) {
        return OCA_FAIL_CALLBACK_UNAVAILABLE;
    }

    if (rsa_3072_verify(digest, signature->bytes, public_key->bytes) != 0) {
        return OCA_FAIL_SIGNATURE;
    }
    return OCA_OK;
}

// -- payload decryption -----------------------------------------------------
//
// The library supplies no cipher and no key material. It has already verified
// payload_hash over the CIPHERTEXT before calling this, and will verify
// payload_hash_chain and every TOC entry hash over the plaintext afterwards, so
// this callback owns exactly three things: resolve the secret, derive the key,
// and run the cipher.
//
// Decrypting IN PLACE is deliberate and explicitly supported: `iv` and
// `kdf_input` point into the manifest body rather than the payload, so
// overwriting the payload cannot disturb the derivation inputs. On a part whose
// staging area is a 256 KiB SRAM, a second payload-sized buffer is not free.
//
// The ciphertext hash being checked first is also what keeps aes_pkcs7_strip()
// off the end of a padding oracle: an attacker cannot submit chosen ciphertexts
// here, because anything they alter fails payload_hash before this runs.

// The provisioned class secret lives in the CLASS_KEY fuse bank (32 bytes).
// encryption_shared_secret_select is a 1-based INDEX naming which provisioned
// secret to use, never key material itself; this part provisions exactly one.
#define OCA_CLASS_KEY_BYTES 32u
#define OCA_SECRET_SLOT_CLASS_KEY 1u

static oca_result_t plat_decrypt_payload(const oca_decrypt_input_t *in,
                                         const uint8_t **out_plaintext, size_t *out_plaintext_len) {
    if (in == NULL || out_plaintext == NULL || out_plaintext_len == NULL ||
        in->ciphertext == NULL || in->iv == NULL || in->kdf_input == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }

    // Confirmed entropy source is functional on entry, as in every crypto callback.
    // The cipher on AES, whose masking PRNG reseeds off EDN before the core will
    // report STATUS.IDLE otherwise
    ENTROPY_PREREQ();

    uint32_t key_bits;
    switch (in->cipher) {
    case OCA_ENCRYPTION_TYPE_AES_128_CBC:
        key_bits = 128u;
        break;
    case OCA_ENCRYPTION_TYPE_AES_256_CBC:
        key_bits = 256u;
        break;
    default:
        // The library already rejects anything else, so this is belt-and-braces
        // rather than the primary gate.
        return OCA_FAIL_DECRYPT;
    }

    if (in->secret_select != OCA_SECRET_SLOT_CLASS_KEY) {
        // A slot this part does not provision. Distinct from a decrypt failure:
        // the image may be perfectly good and simply built for another device.
        simputs("DECRYPT_NO_SECRET\n");
        return OCA_FAIL_NO_PROVISIONED_SECRET;
    }
    if (in->ciphertext_len > (size_t)UINT32_MAX) {
        return OCA_FAIL_INVALID_ARG;
    }

    uint8_t secret[OCA_CLASS_KEY_BYTES];
    fuse_read_bytes(SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR, secret, OCA_CLASS_KEY_BYTES);

    // An erased CLASS_KEY bank is all zeroes. Deriving from it would produce a
    // deterministic key and "successfully" decrypt to garbage, which then fails
    // the plaintext hash with a misleading verdict. Refusing here names the real
    // problem: this part was never provisioned with the secret.
    uint32_t any = 0u;
    for (uint32_t i = 0; i < OCA_CLASS_KEY_BYTES; ++i) {
        any |= secret[i];
    }
    if (any == 0u) {
        simputs("DECRYPT_CLASS_KEY_EMPTY\n");
        explicit_memzero(secret, sizeof secret);
        return OCA_FAIL_NO_PROVISIONED_SECRET;
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_DECRYPTION_START);

    // Release AES from software reset before driving it.
    if (aes_init() != 0) {
        return OCA_FAIL_DECRYPT;
    }

    uint8_t key[32];
    int rc = oca_derive_payload_key(secret, OCA_CLASS_KEY_BYTES, in->kdf_input, key_bits, key);
    explicit_memzero(secret, sizeof secret);
    if (rc != 0) {
        simputs("KDF_FAIL\n");
        explicit_memzero(key, sizeof key);
        return OCA_FAIL_DECRYPT;
    }

    // Cast away const to decrypt in place. The library documents this aliasing
    // as supported and hands us a buffer the ROM itself staged, so the const is
    // about the library's own discipline rather than the memory being read-only.
    uint8_t *buf = (uint8_t *)(uintptr_t)in->ciphertext;
    rc = aes_cbc_decrypt(buf, (uint32_t)in->ciphertext_len, key, key_bits / 8u, in->iv);
    explicit_memzero(key, sizeof key);
    if (rc != 0) {
        simputs("AES_DEC_FAIL\n");
        return OCA_FAIL_DECRYPT;
    }

    uint32_t plain_len = 0u;
    if (aes_pkcs7_strip(buf, (uint32_t)in->ciphertext_len, &plain_len) != 0) {
        return OCA_FAIL_DECRYPT;
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_DECRYPTION_END);
    simputs("DECRYPT_OK\n");

    *out_plaintext = buf;
    *out_plaintext_len = (size_t)plain_len;
    return OCA_OK;
}

// -- root-key authorization (the trust anchor) ------------------------------
//
// The library authenticates a manifest against the key the manifest carries, so
// it can only establish that SOME private key signed it. This is the callback
// that says whose, and it is the reason secure boot decides anything at all.
//
// Slot numbering is NOT this file's invention. public_key_select_classic and the
// CHIPLET_PUBK_REVOKE bitmap index the same key entries -- the RDL says "each key
// entry maps to one bit here" -- so the two must agree bit for bit. If they did
// not, revoking slot N and authorizing slot N would name different keys and
// revocation would be decorative. The map, from CHIPLET_PUBK_REVOKE's own
// description in sep_efuse_map.rdl:
//
//   [5:0]   ROM chiplet-creator classical keys (0,1 are the development keys)
//   [7:6]   reserved
//   [13:8]  ROM chiplet-creator PQC keys
//   [15:14] reserved
//   [17:16] CHIPLET_PUBK_HASH0 / 1
//   [19:18] CHIPLET_PUBK_PQC_HASH0 / 1
//   [21:20] SIP_PUBK_HASH0 / SIP_PUBK_PQC_HASH0
//   [23:22] SYS_PUBK_HASH  / SYS_PUBK_PQC_HASH
//   [25:24] SIP_PUBK_HASH1 / SIP_PUBK_PQC_HASH1
//   [31:26] reserved
//
// The classical OTP slots resolve to a fuse bank; PQC slots are refused because
// nothing here verifies a PQC signature, so authorizing one would hand a key to
// a verifier that cannot check it.
//
// NOTE the addresses are the generated symbols, not the previous ROM's
// CHIPLET_PUBK_REVOKE_BASE + 0x100 / + 0x120 arithmetic, which landed on
// SPI_PHY_DLL_SLAVE and the middle of CHIPLET_PUBK_HASH0. That path was never
// exercised -- only ROM slot 0 is used by any test -- so the bug sat latent.
// The RDL's description text spans the full octets, [7:0] and [15:8]. This ROM
// narrows each: the top two slots of both ROM octets are reserved, so the
// classical band is [5:0] and the PQC band is [13:8]. The narrowing lives here
// because the key model is defined by this file -- the fuse gives 32 bits and
// the manifest gives a bitmap, and nothing but this code assigns them meaning.
// A reserved slot is refused as reserved rather than as unprovisioned: the two
// are different statements, one about the format and one about this part.
#define OCA_KEY_SLOT_ROM_CLASSICAL_LAST 5u          // [5:0]
#define OCA_KEY_SLOT_ROM_CLASSICAL_RESERVED_LAST 7u // [7:6]  reserved
#define OCA_KEY_SLOT_ROM_PQC_LAST 13u               // [13:8]
#define OCA_KEY_SLOT_ROM_PQC_RESERVED_LAST 15u      // [15:14] reserved
#define OCA_KEY_SLOT_MAX 25u                        // [31:26] reserved

// Low 32 flags of a 16-byte OCA flag field, for the console echoes below.
static uint32_t oca_flags_low32(const uint8_t *f) {
    return (uint32_t)f[0] | ((uint32_t)f[1] << 8) | ((uint32_t)f[2] << 16) | ((uint32_t)f[3] << 24);
}

// Resolve a classical OTP key slot to its digest bank. Returns false for a slot
// that is not a classical OTP anchor (PQC, or out of the defined range).
static bool otp_key_digest_addr(uint32_t slot, uint32_t *out_addr) {
    switch (slot) {
    case 16u:
        *out_addr = SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH0_BASE_ADDR;
        return true;
    case 17u:
        *out_addr = SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH1_BASE_ADDR;
        return true;
    case 20u:
        *out_addr = SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH0_BASE_ADDR;
        return true;
    case 22u:
        *out_addr = SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_HASH_BASE_ADDR;
        return true;
    // SIP_PUBK_HASH1 is a real bank in the RDL (@0x260) but the VP eFuse model
    // has no register there yet, so a run selecting slot 24 reads reserved space
    // rather than a provisioned digest. Mapped for correctness against silicon;
    // not exercisable on sep-vp until the model is re-synced.
    case 24u:
        *out_addr = SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH1_BASE_ADDR;
        return true;
    default:
        return false;
    }
}

static oca_result_t plat_is_key_authorized(const oca_crypto_blob_t *public_key,
                                           const uint8_t select[16]) {
    if (public_key == NULL || select == NULL || public_key->bytes == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }
    // Only RSA-3072 raw keys can be anchored: the digests are over a 384-byte
    // modulus. Refusing anything else here keeps this from silently hashing a
    // differently shaped field and comparing it to an unrelated digest.
    //
    // The library gives this callback one failure code, so all three refusals
    // below surface as ROOT_KEY_UNAUTHORIZED. They are very different problems --
    // an unsigned image on a part that demands signing, an algorithm this ROM
    // does not implement, and an encoding it does not parse -- so each gets its
    // own console marker. Without them a triage starts from "invalid key hash",
    // which is the one thing none of them is.
    if (public_key->primitive_type == OCA_PRIMITIVE_NONE) {
        simputs("PUBK_NO_SIGNATURE\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }
    if (public_key->primitive_type != OCA_PRIMITIVE_RSA_3072_PKCS1V15_SHA256) {
        simputs("PUBK_ALGO_UNSUPPORTED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }
    if (public_key->encoding != OCA_ENCODING_RAW) {
        simputs("PUBK_ENCODING_UNSUPPORTED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }
    if (public_key->field_length < OCA_RSA3072_PUBKEY_BYTES) {
        simputs("PUBK_FIELD_TOO_SMALL\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }

    // public_key_select is a 128-bit bitmap. Resolve it to the one slot it
    // names; more than one set bit is ambiguous about which anchor applies, so
    // refuse rather than pick.
    int slot = -1;
    for (uint32_t bit = 0; bit < 128u; ++bit) {
        if ((select[bit / 8u] >> (bit % 8u)) & 1u) {
            if (slot >= 0) {
                simputs("PUBK_SEL_AMBIGUOUS\n");
                return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
            }
            slot = (int)bit;
        }
    }
    if (slot < 0) {
        simputs("PUBK_SEL_EMPTY\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }

    // The slot number, not just the verdict: every refusal below names a
    // reason but not which anchor was asked for, and DV attributes a key
    // decision to a slot.
    simputshex32("PUBK_SEL=", (uint32_t)slot);

    if ((uint32_t)slot > OCA_KEY_SLOT_MAX) {
        // [31:26] are reserved. A manifest naming one is not describing a key
        // this format defines, let alone one this part holds.
        simputs("PUBK_SLOT_RESERVED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }

    uint8_t anchor[32];
    if ((uint32_t)slot <= OCA_KEY_SLOT_ROM_CLASSICAL_LAST) {
        // ROM classical key. The band and key_digests.c agree by construction
        // (NUM_PUBLIC_KEY_DIGESTS is PUBK_SEL_NUM_ROM_KEYS), so the guard below
        // is unreachable with the shipped table. It stays because it is the
        // fail-closed one: a NULL digest is not a licence to skip the hash
        // check, which would accept any key naming an empty slot.
        if ((uint32_t)slot >= NUM_PUBLIC_KEY_DIGESTS || public_key_digests[slot].digest == NULL) {
            simputs("PUBK_SLOT_UNPROVISIONED\n");
            return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
        }
        const uint8_t *rom_digest = public_key_digests[slot].digest;
        for (uint32_t i = 0; i < 32u; ++i) {
            anchor[i] = rom_digest[i];
        }
    } else if ((uint32_t)slot <= OCA_KEY_SLOT_ROM_CLASSICAL_RESERVED_LAST) {
        // [7:6]. Reserved, not merely unheld: no part of this generation may
        // assign them, so the refusal names the format rather than this device.
        simputs("PUBK_SLOT_RESERVED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    } else if ((uint32_t)slot <= OCA_KEY_SLOT_ROM_PQC_LAST) {
        // ROM PQC key. Refused rather than resolved: nothing here verifies a PQC
        // signature, so authorizing one would hand a key to a verifier that
        // cannot check it, and the manifest would fail later with a code that
        // blames the signature rather than the unsupported algorithm.
        simputs("PUBK_SLOT_PQC_UNSUPPORTED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    } else if ((uint32_t)slot <= OCA_KEY_SLOT_ROM_PQC_RESERVED_LAST) {
        // [15:14]. Reserved for the same reason as [7:6], and refused as
        // reserved rather than as PQC: the slot is not a PQC key this build
        // declines to verify, it is not a key at all.
        simputs("PUBK_SLOT_RESERVED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    } else {
        uint32_t addr;
        if (!otp_key_digest_addr((uint32_t)slot, &addr)) {
            // A defined-but-PQC OTP slot (18, 19, 21, 23, 25), for the same
            // reason as above.
            simputs("PUBK_SLOT_PQC_UNSUPPORTED\n");
            return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
        }
        fuse_read_bytes(addr, anchor, 32u);
        // An erased OTP bank is all zeroes and must not be an anchor anything
        // can match; a key whose SHA-256 is zero is not a realistic forgery, but
        // an unburned part accepting a zero digest would be.
        uint32_t any = 0u;
        for (uint32_t i = 0; i < 32u; ++i) {
            any |= anchor[i];
        }
        if (any == 0u) {
            simputs("PUBK_OTP_EMPTY\n");
            return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
        }
    }

    // Digest the modulus only (384 B), not the 388-byte RAW blob, so the digests
    // key_digests.c already ships stay valid across the format change and
    // tools/generate_key_digests.py needs no rework.
    uint8_t digest[32];
    if (sha256(public_key->bytes, 384u, digest) != 0) {
        simputs("PUBK_HASH_TIMEOUT\n");
        return OCA_FAIL_CALLBACK_UNAVAILABLE;
    }

    // Constant time: the anchor is not secret, but the comparison is
    // attacker-driven and an early exit leaks how much of a forged key matched.
    uint32_t diff = 0u;
    for (uint32_t i = 0; i < 32u; ++i) {
        diff |= (uint32_t)(digest[i] ^ anchor[i]);
    }
    if (diff != 0u) {
        simputs("PUBK_UNAUTHORIZED\n");
        return OCA_FAIL_ROOT_KEY_UNAUTHORIZED;
    }
    simputs("PUBK_AUTHORIZED\n");
    return OCA_OK;
}

// -- OTP identity / lifecycle / version -------------------------------------

static oca_hw_result_t plat_get_identity_bytes(oca_id_kind_t field, uint8_t out[32]) {
    uint32_t base;

    if (out == NULL) {
        return OCA_HW_ERROR;
    }
    switch (field) {
    case OCA_ID_CHIPLET:
        base = SEP_TOP_SEP_EFUSE_MAP_SEP_CHIPLET_ID_BASE_ADDR;
        break;
    case OCA_ID_PACKAGE:
        base = SEP_TOP_SEP_EFUSE_MAP_SEP_SIP_ID_BASE_ADDR;
        break;
    case OCA_ID_SYSTEM:
        base = SEP_TOP_SEP_EFUSE_MAP_SEP_SYS_ID_BASE_ADDR;
        break;
    default:
        return OCA_HW_ERROR;
    }
    fuse_read_bytes(base, out, OCA_IDENTITY_BYTES);
    return OCA_HW_OK;
}

static oca_hw_result_t plat_get_lifecycle_state(oca_lifecycle_level_t level,
                                                oca_lifecycle_token_t *out_state) {
    if (out_state == NULL) {
        return OCA_HW_ERROR;
    }
    // Write the output before any early return: the contract asks for
    // OCA_LIFECYCLE_UNKNOWN rather than an untouched buffer.
    *out_state = OCA_LIFECYCLE_UNKNOWN;

    // SEP fuses carry a chiplet lifecycle only. Package and system levels are
    // not provisioned on this part, and OCA_HW_UNAVAILABLE is the honest answer
    // -- it fails the manifest, which is correct: a manifest constraining a
    // level this device cannot report must not boot on it.
    if (level != OCA_LIFECYCLE_LEVEL_CHIPLET) {
        return OCA_HW_UNAVAILABLE;
    }

    uint32_t lc = lc_read_state();
    if (!lc_state_is_valid(lc)) {
        return OCA_HW_ERROR;
    }

    // Decoded SEP encoding -> the manifest's own token values. Deliberately a
    // switch rather than arithmetic: the two encodings agree on nothing, and the
    // SEP RMA states are ranges (lifecycle.h LC_STATE_RMA_*_LO/HI).
    switch (lc) {
    case LC_STATE_TEST_DEV:
        *out_state = OCA_LIFECYCLE_TEST_DEV;
        break;
    case LC_STATE_PROD:
        *out_state = OCA_LIFECYCLE_PROD;
        break;
    case LC_STATE_PROD_END:
        *out_state = OCA_LIFECYCLE_PROD_END;
        break;
    case LC_STATE_RMA_SIP_LO:
    case LC_STATE_RMA_SIP_HI:
        *out_state = OCA_LIFECYCLE_RMA_SIP;
        break;
    case LC_STATE_RMA_CHIPLET_LO:
    case 0x5u:
    case 0x6u:
    case LC_STATE_RMA_CHIPLET_HI:
        *out_state = OCA_LIFECYCLE_RMA_CHIPLET;
        break;
    default:
        return OCA_HW_ERROR;
    }
    return OCA_HW_OK;
}

static oca_hw_result_t plat_get_version(oca_version_level_t level, uint16_t *out_major,
                                        uint16_t *out_minor) {
    (void)level;
    if (out_major == NULL || out_minor == NULL) {
        return OCA_HW_ERROR;
    }
    // No version-range fuses are provisioned on SEP. Reporting UNAVAILABLE makes
    // a manifest that constrains a version range fail closed; the test configs
    // do not set one, so this is never reached by the current images.
    *out_major = 0;
    *out_minor = 0;
    return OCA_HW_UNAVAILABLE;
}

// -- secure-boot posture ----------------------------------------------------
//
// Both reporters must be stable for a whole validation: the library re-derives
// the determination at every gated check and compares it against the recorded
// one, so a value that changes mid-validation is OCA_FAIL_SECURE_BOOT_STATE_
// CHANGED. Both read fuse shadows that are frozen well before this point.

static oca_secure_bool_t plat_is_secure_boot_active(void) {
    uint32_t lc = lc_read_state();
    return lc_state_enforces_secure_boot(lc) ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;
}

static oca_secure_bool_t plat_is_secure_boot_disabled(void) {
    // The value [S18] latched, not a fresh read of the shadow. rsvd[31:1] is
    // driven from the fuse array, so a whole-word test here would let any of 31
    // bits disable enforcement while bl0_state and the boot measurement -- which
    // mask -- recorded that it had not been disabled.
    //
    // Latched rather than re-read so this answer cannot move mid-validation:
    // the library rejects a determination that changes under it, and the [S18]
    // sample is the one taken before any untrusted input was staged.
    return sboot_dis_disabled() ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;
}

// -- device-stored secure-boot state (reads only) ---------------------------

static oca_result_t plat_get_root_key_revocation(oca_key_algorithm_t algo, uint8_t out[16]) {
    if (out == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }
    for (uint32_t i = 0; i < 16u; ++i) {
        out[i] = 0u;
    }
    if (algo != OCA_KEY_ALGO_CLASSIC) {
        // No PQC revocation fuses are provisioned. An all-zero bitmap revokes
        // nothing, which is the right answer for a device that cannot revoke a
        // class of key it also cannot verify.
        return OCA_OK;
    }
    // CHIPLET_PUBK_REVOKE is a single 32-bit bank (next base is 4 bytes on), so
    // only the low 32 of the 128 revocation bits are backed by fuses here. The
    // rest stay zero.
    fuse_read_bytes(SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR, out, 4u);
    simputshex32("PUBK_REVOKE=", oca_flags_low32(out));
    return OCA_OK;
}

static oca_result_t plat_get_security_version(uint8_t out[16]) {
    if (out == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }
    // The library's test is `manifest & device == device` -- the manifest must
    // be a bit-superset of what the device has accumulated. eFuse bits only ever
    // go 0 -> 1, so the raw fuse image is already exactly that monotone bit set;
    // no thermometer-to-count conversion belongs here.
    //
    // BL1_VERSION is a 32-byte bank; only its low 16 bytes map onto OCA's
    // 128-bit field. Anything set above bit 127 cannot be expressed and is not
    // read.
    fuse_read_bytes(SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR, out, 16u);

    // The device's side of the rollback comparison. The verdict is a single
    // result code, so which flags the device holds is not recoverable from it.
    // Low 32 flags only -- that is the width the fuse bank backs. The manifest's
    // side is echoed by oca_boot.c before validation, where the staged body is
    // in hand.
    simputshex32("FUSE_VER=", oca_flags_low32(out));
    return OCA_OK;
}

// -- the table --------------------------------------------------------------
//
// Designated initialisers, so the unwired entries are explicit by absence and a
// callback added upstream defaults to NULL (fail-closed) rather than to whatever
// the next field happened to be.
//
// set_root_key_revocation / set_security_version / set_signature_cohort_enforce
// / set_signature_class_revoke are deliberately absent: the ROM has no OTP
// programming path, and oca_commit_security_state() is not called. Anti-rollback
// and revocation are therefore *enforced* against the fuses but never *advanced*
// by a successful boot. Wiring these means adding an irreversible-write driver.
//
// describe_field is diagnostics-only and costs ROM for string tables, so it is
// left out as well.
static const oca_callbacks_t sep_callbacks = {
    .sha256 = plat_sha256,
    .verify_signature = plat_verify_signature,
    .decrypt_payload = plat_decrypt_payload,
    .get_identity_bytes = plat_get_identity_bytes,
    .get_lifecycle_state = plat_get_lifecycle_state,
    .get_version = plat_get_version,
    .is_secure_boot_active = plat_is_secure_boot_active,
    .is_secure_boot_disabled = plat_is_secure_boot_disabled,
    .is_key_authorized = plat_is_key_authorized,
    .get_root_key_revocation = plat_get_root_key_revocation,
    .get_security_version = plat_get_security_version,
};

const oca_callbacks_t *sep_oca_callbacks(void) {
    return &sep_callbacks;
}
