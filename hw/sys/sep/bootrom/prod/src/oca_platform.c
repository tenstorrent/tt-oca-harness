// SPDX-License-Identifier: Apache-2.0
//
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
#include "hmac_sha256.h"
#include "lifecycle.h"
#include "rom_mmio.h"
#include "rsa_verify.h"
#include "sep_addr.h"

// RAW RSA-3072 public key: 384-byte big-endian modulus followed by a 4-byte
// big-endian exponent (openssl_crypto.c rsa_key_from_raw is the reference).
#define OCA_RSA3072_MODULUS_BYTES  384u
#define OCA_RSA3072_EXPONENT_BYTES 4u
#define OCA_RSA3072_PUBKEY_BYTES   (OCA_RSA3072_MODULUS_BYTES + OCA_RSA3072_EXPONENT_BYTES)
#define OCA_RSA3072_SIGNATURE_BYTES 384u

// The only exponent the OTBN app implements: it is built as
// MODE_RSA_3072_MODEXP_F4, so e is wired to F4 and never read from the key.
// A key carrying any other exponent would otherwise be verified against 65537
// regardless of what it says, which is a silent wrong-key accept.
#define OCA_RSA_EXPONENT_F4 0x00010001u

// Identity banks are 32 bytes each (base-address deltas in sep_addr.h), which is
// exactly the width get_identity_bytes must fill.
#define OCA_IDENTITY_BYTES 32u

// Read a little-endian byte image out of a 32-bit-word eFuse shadow bank.
// Matches the existing manifest_crypto.c fuse readers: word[0] holds bits[31:0]
// and byte 0 is that word's LSB.
static void fuse_read_bytes(uint32_t base, uint8_t *out, uint32_t len)
{
    for (uint32_t i = 0; i < len; i += 4u) {
        uint32_t val = mmio_read32(base + i);
        out[i]      = (uint8_t)(val);
        out[i + 1u] = (uint8_t)(val >> 8);
        out[i + 2u] = (uint8_t)(val >> 16);
        out[i + 3u] = (uint8_t)(val >> 24);
    }
}

static uint32_t be32_load(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16)
         | ((uint32_t)p[2] << 8)  | (uint32_t)p[3];
}

// -- hashing ----------------------------------------------------------------

static oca_result_t plat_sha256(const uint8_t *msg, size_t msg_len, uint8_t out_digest[32])
{
    if (msg == NULL || out_digest == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }
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
                                          const uint8_t *signed_region,
                                          size_t signed_region_len)
{
    uint8_t digest[32];

    if (signature == NULL || public_key == NULL || signed_region == NULL) {
        return OCA_FAIL_INVALID_ARG;
    }

    // RSA-3072 PKCS#1 v1.5 / SHA-256 only. ECDSA P-256 (0x05) is a valid OCA
    // primitive the ROM has no verifier for, and the PQC variants carry no
    // native signature the library can check either. Refusing here is the clean
    // "unsupported" the format expects -- never a pass.
    if (signature->primitive_type != OCA_PRIMITIVE_RSA_3072_PKCS1V15_SHA256
        || public_key->primitive_type != OCA_PRIMITIVE_RSA_3072_PKCS1V15_SHA256) {
        return OCA_FAIL_SIGNATURE;
    }

    // RAW only: DER would mean an ASN.1 parser inside a 64 KiB ROM, and the
    // producer configs pin raw encoding for exactly that reason.
    if (signature->encoding != OCA_ENCODING_RAW
        || public_key->encoding != OCA_ENCODING_RAW) {
        return OCA_FAIL_SIGNATURE;
    }

    // field_length is the manifest field width, not the encoded length, so this
    // is a "does the field even hold the primitive" check.
    if (signature->field_length < OCA_RSA3072_SIGNATURE_BYTES
        || public_key->field_length < OCA_RSA3072_PUBKEY_BYTES) {
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

// -- OTP identity / lifecycle / version -------------------------------------

static oca_hw_result_t plat_get_identity_bytes(oca_id_kind_t field, uint8_t out[32])
{
    uint32_t base;

    if (out == NULL) {
        return OCA_HW_ERROR;
    }
    switch (field) {
    case OCA_ID_CHIPLET: base = OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_CHIPLET_ID_BASE_ADDR; break;
    case OCA_ID_PACKAGE: base = OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SIP_ID_BASE_ADDR;     break;
    case OCA_ID_SYSTEM:  base = OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SYS_ID_BASE_ADDR;     break;
    default:             return OCA_HW_ERROR;
    }
    fuse_read_bytes(base, out, OCA_IDENTITY_BYTES);
    return OCA_HW_OK;
}

static oca_hw_result_t plat_get_lifecycle_state(oca_lifecycle_level_t level,
                                                oca_lifecycle_token_t *out_state)
{
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

static oca_hw_result_t plat_get_version(oca_version_level_t level,
                                        uint16_t *out_major, uint16_t *out_minor)
{
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

static oca_secure_bool_t plat_is_secure_boot_active(void)
{
    uint32_t lc = lc_read_state();
    return lc_state_enforces_secure_boot(lc) ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;
}

static oca_secure_bool_t plat_is_secure_boot_disabled(void)
{
    // Same SBOOT_DIS shadow rom_main.c latches into bl0_state, read directly so
    // this stays usable no matter the order callbacks are first invoked in.
    uint32_t sboot_dis = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR);
    return (sboot_dis != 0u) ? OCA_SECURE_TRUE : OCA_SECURE_FALSE;
}

// -- device-stored secure-boot state (reads only) ---------------------------

static oca_result_t plat_get_root_key_revocation(oca_key_algorithm_t algo, uint8_t out[16])
{
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
    fuse_read_bytes(OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR, out, 4u);
    return OCA_OK;
}

static oca_result_t plat_get_security_version(uint8_t out[16])
{
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
    // read -- see the note in OCA_MANIFEST_PLAN.md.
    fuse_read_bytes(OCH_SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR, out, 16u);
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
    .sha256                 = plat_sha256,
    .verify_signature       = plat_verify_signature,
    .decrypt_payload        = NULL,  // Phase 4: AES-256-CBC + PKCS#7 + OCA KDF
    .get_identity_bytes     = plat_get_identity_bytes,
    .get_lifecycle_state    = plat_get_lifecycle_state,
    .get_version            = plat_get_version,
    .is_secure_boot_active  = plat_is_secure_boot_active,
    .is_secure_boot_disabled = plat_is_secure_boot_disabled,
    .get_root_key_revocation = plat_get_root_key_revocation,
    .get_security_version   = plat_get_security_version,
};

const oca_callbacks_t *sep_oca_callbacks(void)
{
    return &sep_callbacks;
}
