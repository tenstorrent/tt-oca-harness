/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Manifest crypto validation for OROM (C13.10).
//
// Orchestrates all cryptographic checks on a loaded manifest:
//   (a) BL1 version rollback check (thermometer-encoded fuse vs manifest)
//   (b) Public key revocation check (CHIPLET_PUBK_REVOKE fuse bitmap)
//   (c) RSA-3072 signature verification (OTBN + PKCS#1 v1.5)
//   (d) Payload hash verification (SHA-256 of payload data)
//   (e) Payload decryption (AES-128-CBC with KBKDF-HMAC-SHA256)
//
// Reference flow for manifest crypto validation,
// key/fuse helpers, and payload processing.

#include "manifest_crypto.h"
#include "manifest.h"
#include "hmac_sha256.h"
#include "rsa_verify.h"
#include "aes_driver.h"
#include "kdf.h"
#include "key_digests.h"
#include "bl0_state.h"
#include "lifecycle.h"
#include "errors.h"
#include "rom_mmio.h"
#include "sep.h"

#include <stdbool.h>
#include <stdint.h>

// Fuse key length for reading raw public key hashes from fuses.
// The value stores a 32-byte SHA-256 digest.
#define FUSE_KEY_LENGTH 32

// CHIPLET_PUBK_REVOKE bit assignments, from the field description in
// hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl. ROM slots occupy
// [7:0] so a slot index doubles as its own bit, but the fused keys do NOT
// continue that sequence -- they sit at 16 and above. Deriving them as
// PUBK_SEL_NUM_ROM_KEYS + n gave bits 6 and 7, which are unused ROM-slot bits
// and therefore always clear, so revoking a fused key had no effect at all.
#define PUBK_REVOKE_BIT_CHIPLET_HASH0 16
#define PUBK_REVOKE_BIT_CHIPLET_HASH1 17
#define PUBK_REVOKE_BIT_SIP_HASH0 20
#define PUBK_REVOKE_BIT_SYS_HASH 22
#define PUBK_REVOKE_BIT_SIP_HASH1 24

// Max KDF argument bytes.
#define MAX_KDF_ARGUMENT_BYTES 16

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Constant-time byte comparison (prevents timing side-channel).
static bool const_time_eq(const uint8_t *a, const uint8_t *b, uint32_t len) {
    volatile uint8_t diff = 0;
    for (uint32_t i = 0; i < len; ++i) {
        diff |= a[i] ^ b[i];
    }
    return diff == 0;
}

// explicit_memzero() is provided by sep_helpers.h (included via manifest.h).

// ---------------------------------------------------------------------------
// (a) Version rollback check
// ---------------------------------------------------------------------------

// Read security version from fuse (thermometer encoding: count 1-bits).
// BL1_VERSION is 8 × 32-bit words = 256 bits; version = popcount.
// Reference logic for security version decoding.
static uint32_t get_security_version_from_fuse(uint32_t reg_addr) {
    uint32_t version = 0;
    for (uint32_t i = 0; i < 8u; ++i) {
        uint32_t w = mmio_read32(reg_addr + i * 4u);
        // popcount via Kernighan's bit-counting.
        while (w) {
            w &= w - 1u;
            ++version;
        }
    }
    return version;
}

// Check that the manifest's security_version is >= the fuse version.
// Reference logic for security version comparison.
static uint32_t check_security_version(uint16_t manifest_ver, uint32_t fuse_addr) {
    uint32_t fuse_ver = get_security_version_from_fuse(fuse_addr);
    report_status(STATUS_TYPE_INFO, SEP_MSG_READ_BL1_SECURITY_VERSION);
    simputshex32("FUSE_VER=", fuse_ver);
    simputshex32("MFST_VER=", (uint32_t)manifest_ver);

    if ((uint32_t)manifest_ver < fuse_ver) {
        simputs("VERSION_ROLLBACK\n");
        return MANIFEST_ERR_VERSION_ROLLBACK;
    }
    return MANIFEST_OK;
}

// ---------------------------------------------------------------------------
// (b) Public key revocation check
// ---------------------------------------------------------------------------

// Check if a key has been revoked via the CHIPLET_PUBK_REVOKE fuse.
// Reference logic for key revocation checks.
static uint32_t check_pubkey_revoked(int revocation_index) {
    uint32_t revoke = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR);
    simputshex32("PUBK_REVOKE=", revoke);

    if (revoke & (1u << (uint32_t)revocation_index)) {
        simputshex32("KEY_REVOKED idx=", (uint32_t)revocation_index);
        return MANIFEST_ERR_KEY_REVOKED;
    }
    return MANIFEST_OK;
}

// ---------------------------------------------------------------------------
// (c) RSA-3072 signature verification helpers
// ---------------------------------------------------------------------------

// Verify public key hash: SHA-256 of manifest modulus vs expected digest.
// Reference logic for public key hash checks.
static uint32_t check_pubkey_hash(const uint8_t *pub_key, const uint8_t *expected_digest) {
    uint8_t digest[32];
    if (sha256(pub_key, RSA_3072_KEY_SZ_BYTES, digest) != 0) {
        simputs("PUBK_HASH_TIMEOUT\n");
        return MANIFEST_ERR_SIG_FAILED;
    }

    if (!const_time_eq(digest, expected_digest, 32)) {
        simputs("PUBK_HASH_MISMATCH\n");
        return MANIFEST_ERR_KEY_HASH_MISMATCH;
    }
    return MANIFEST_OK;
}

// Read a fuse key digest (32 bytes) from the given fuse address.
// Returns true if at least one byte is non-zero.
static bool read_fuse_key(uint32_t fuse_addr, uint8_t *key) {
    bool non_zero = false;
    for (uint32_t i = 0; i < FUSE_KEY_LENGTH / 4u; ++i) {
        uint32_t val = mmio_read32(fuse_addr + i * 4u);
        key[i * 4] = (uint8_t)(val);
        key[i * 4 + 1] = (uint8_t)(val >> 8);
        key[i * 4 + 2] = (uint8_t)(val >> 16);
        key[i * 4 + 3] = (uint8_t)(val >> 24);
        if (val != 0u) non_zero = true;
    }
    return non_zero;
}

// Full signature validation: key selection → revocation → hash → RSA verify.
// Reference flow for full signature validation.
static uint32_t validate_signature(const manifest_t *m, uint32_t lc_state) {
    uint32_t err;
    const uint8_t *signature = m->signature.rsa_signature;
    const uint8_t *pub_key = m->public_key.rsa_modulus;
    int revocation_index;

    // Only RSA-3072 is supported.
    if (m->signature_type != MANIFEST_SIG_TYPE_RSA_3072) {
        simputshex32("BAD_SIG_TYPE=", (uint32_t)m->signature_type);
        return MANIFEST_ERR_SIG_FAILED;
    }

    simputshex32("PUBK_SEL=", (uint32_t)m->public_key_sel.value);

    // Determine key source and expected digest.
    if (m->public_key_sel.selection == PUBK_SEL_ROM_KEY) {
        // ROM key slot.
        report_status(STATUS_TYPE_INFO, SEP_MSG_VALIDATE_CHECK);
        uint16_t index = m->public_key_sel.index;
        if (index >= PUBK_SEL_NUM_ROM_KEYS) {
            simputs("BAD_KEY_IDX\n");
            return MANIFEST_ERR_SIG_FAILED;
        }

        // ROM key revocation.
        revocation_index = (int)index;
        err = check_pubkey_revoked(revocation_index);
        if (err) return err;

        // ROM key hash validation. The modulus is taken from the manifest, so
        // binding it to a compiled-in digest is the only thing that makes the
        // signature mean anything. An unpopulated slot must therefore be
        // rejected, not skipped: skipping leaves a manifest free to select that
        // slot, pass revocation (its fuse bit is 0) and RSA-verify against its
        // own modulus. Same fail-closed rule as the fuse path below.
        const public_key_info_t *ki = &public_key_digests[index];
        if (ki->digest == (void *)0) {
            simputs("ROM_KEY_EMPTY\n");
            return MANIFEST_ERR_SIG_FAILED;
        }
        err = check_pubkey_hash(pub_key, ki->digest);
        if (err) return err;
    } else {
        // Fuse key slot.
        uint32_t fuse_addr;
        uint8_t fuse_key[FUSE_KEY_LENGTH];

        switch (m->public_key_sel.selection) {
        // Address the digest fuses by name. The previous form derived them as
        // CHIPLET_PUBK_REVOKE + 0x100/0x120, which lands 0x10 below
        // CHIPLET_PUBK_HASH0/HASH1 and so read the wrong fuse words.
        case PUBK_SEL_FUSE_KEY_0:
            fuse_addr = OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH0_BASE_ADDR;
            revocation_index = PUBK_REVOKE_BIT_CHIPLET_HASH0;
            break;
        case PUBK_SEL_FUSE_KEY_1:
            fuse_addr = OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH1_BASE_ADDR;
            revocation_index = PUBK_REVOKE_BIT_CHIPLET_HASH1;
            break;
        case PUBK_SEL_FUSE_SOP_KEY:
            fuse_addr = OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH0_BASE_ADDR;
            revocation_index = PUBK_REVOKE_BIT_SIP_HASH0;
            break;
        case PUBK_SEL_FUSE_SYS_KEY:
            fuse_addr = OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_HASH_BASE_ADDR;
            revocation_index = PUBK_REVOKE_BIT_SYS_HASH;
            break;
        default:
            simputs("BAD_KEY_SEL\n");
            return MANIFEST_ERR_SIG_FAILED;
        }

        // Fuse key revocation.
        err = check_pubkey_revoked(revocation_index);
        if (err) return err;

        // Read fuse key digest and validate.
        if (!read_fuse_key(fuse_addr, fuse_key)) {
            simputs("FUSE_KEY_EMPTY\n");
            return MANIFEST_ERR_SIG_FAILED;
        }
        err = check_pubkey_hash(pub_key, fuse_key);
        explicit_memzero(fuse_key, FUSE_KEY_LENGTH);
        if (err) return err;
    }

    // RSA-3072 signature verification.
    report_status(STATUS_TYPE_DEBUG, SEP_MSG_VALIDATE_CHECK);
    simputs("RSA_VERIFY_START\n");
    if (rsa_3072_verify(m->manifest_hash, signature, pub_key) != 0) {
        simputs("RSA_VERIFY_FAIL\n");
        return MANIFEST_ERR_SIG_FAILED;
    }

    simputs("SIG_VALID\n");
    return MANIFEST_OK;
}

// ---------------------------------------------------------------------------
// (d) Payload hash verification
// ---------------------------------------------------------------------------

uint32_t verify_payload_hash(const manifest_t *m) {
    const uint8_t *payload = (const uint8_t *)m + (uint32_t)m->boot_arguments.payload_offset;
    uint32_t hash_len = (uint32_t)m->payload_hashed_length;

    if (hash_len == 0u) {
        // No payload hash to verify (payload_hashed_length = 0).
        return MANIFEST_OK;
    }

    uint8_t digest[32];
    if (sha256(payload, hash_len, digest) != 0) {
        simputs("PLD_HASH_TIMEOUT\n");
        return MANIFEST_ERR_HASH_MISMATCH;
    }

    if (!const_time_eq(digest, m->payload_hash, 32)) {
        simputs("PLD_HASH_MISMATCH\n");
        return MANIFEST_ERR_PAYLOAD_HASH_MISMATCH;
    }

    simputs("PLD_HASH_OK\n");
    return MANIFEST_OK;
}

// ---------------------------------------------------------------------------
// (e) Payload decryption
// ---------------------------------------------------------------------------

// Read encryption class_key from fuse (32 bytes = 8 × 32-bit words).
// OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR = 0x10930064
static void get_enc_key(uint8_t *key) {
    for (uint32_t i = 0; i < FUSE_KEY_LENGTH / 4u; ++i) {
        uint32_t val = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR + i * 4u);
        key[i * 4] = (uint8_t)(val);
        key[i * 4 + 1] = (uint8_t)(val >> 8);
        key[i * 4 + 2] = (uint8_t)(val >> 16);
        key[i * 4 + 3] = (uint8_t)(val >> 24);
    }
}

static uint32_t decrypt_payload(const manifest_t *m) {
    uint8_t class_key[FUSE_KEY_LENGTH];
    uint8_t derived_key[AES_KEY_SIZE_BYTES];
    uint8_t info[MAX_KDF_ARGUMENT_BYTES];
    uint8_t salt[MAX_KDF_ARGUMENT_BYTES];
    uint32_t rc = MANIFEST_OK;

    simputs("DECRYPT_START\n");

    // Read class_key from fuse.
    get_enc_key(class_key);

    // Split manifest KDF input into info (first half) and salt (second half).
    for (uint32_t i = 0; i < MAX_KDF_ARGUMENT_BYTES; ++i) {
        info[i] = m->encryption_kdf_input[i];
    }
    for (uint32_t i = 0; i < MAX_KDF_ARGUMENT_BYTES; ++i) {
        salt[i] = m->encryption_kdf_input[MAX_KDF_ARGUMENT_BYTES + i];
    }

    // Derive AES key via KBKDF-HMAC-SHA256.
    if (kbkdf_hmac_sha256(class_key, FUSE_KEY_LENGTH, info, salt, derived_key,
                          AES_KEY_SIZE_BYTES) != 0) {
        simputs("KDF_FAIL\n");
        rc = MANIFEST_ERR_DECRYPT_FAILED;
        goto cleanup;
    }

    // Initialize AES hardware.
    if (aes_init() != 0) {
        simputs("AES_INIT_FAIL\n");
        rc = MANIFEST_ERR_DECRYPT_FAILED;
        goto cleanup;
    }

    // Decrypt payload in-place (manifest is in SRAM, cast away const).
    uint8_t *payload = (uint8_t *)(uintptr_t)m + (uint32_t)m->boot_arguments.payload_offset;
    if (aes128cbc_decrypt(payload, (uint32_t)m->payload_length, derived_key, m->encryption_iv) !=
        0) {
        simputs("AES_DEC_FAIL\n");
        rc = MANIFEST_ERR_DECRYPT_FAILED;
        goto cleanup;
    }

    simputs("DECRYPT_OK\n");

cleanup:
    explicit_memzero(derived_key, AES_KEY_SIZE_BYTES);
    explicit_memzero(class_key, FUSE_KEY_LENGTH);
    explicit_memzero(info, MAX_KDF_ARGUMENT_BYTES);
    explicit_memzero(salt, MAX_KDF_ARGUMENT_BYTES);
    return rc;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

uint32_t manifest_crypto_validate(const manifest_t *m, uint32_t lc_state) {
    uint32_t err;

    report_status(STATUS_TYPE_INFO, SEP_MSG_VALIDATE_CHECK);

    // ── (a) Version rollback check ──
    // Check manifest security_version against BL1_VERSION fuse.
    // If the manifest flags indicate version update is requested,
    // we still validate (update happens after successful boot in BL1).
    err = check_security_version(m->security_version,
                                 OCH_SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR);
    if (err) return err;

    // ── (c) Signature verification (includes (b) key revocation) ──
    err = validate_signature(m, lc_state);
    if (err) return err;

    // ── (d) Payload hash — verified BEFORE decryption ──
    // The packer hashes the ALREADY-ENCRYPTED payload (pack_images.py), so
    // payload_hash covers ciphertext: this is the only order in which the hash
    // means anything for an encrypted image, and it is authenticate-before-
    // process -- nothing reaches the decryption engine unverified.
    err = verify_payload_hash(m);
    if (err) return err;

    // ── (e) Payload decryption (if encrypted) ──
    {
        bool encrypted = (m->usage_constraints.flags &
                          (1u << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD)) != 0;
        if (encrypted) {
            err = decrypt_payload(m);
            if (err) return err;
        }
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_MANIFEST_VALIDATED);
    simputs("CRYPTO_VALIDATE_OK\n");
    return MANIFEST_OK;
}
