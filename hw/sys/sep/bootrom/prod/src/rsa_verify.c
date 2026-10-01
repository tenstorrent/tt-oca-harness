// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// RSA-3072 signature verification for OROM.
//
// Uses OTBN coprocessor for modular exponentiation (signature^e mod n)
// and verifies PKCS#1 v1.5 padding structure with SHA-256 digest.
//
// OTBN stores big numbers in little-endian word order:
//   word[0]  = least-significant 32 bits
//   word[95] = most-significant 32 bits (for RSA-3072 = 384 bytes)
//
// PKCS#1 v1.5 padded message (384 bytes, big-endian byte order):
//   [0x00] [0x01] [0xFF x 330] [0x00] [DigestInfo 19 bytes] [Hash 32 bytes]
//
// In OTBN word order:
//   words[0..7]   = SHA-256 hash (reversed word order, big-endian per word)
//   words[8..12]  = DigestInfo + 0x00 separator
//   words[13..94] = 0xFFFFFFFF (padding)
//   word[95]      = 0x0001FFFF (header)

#include "rsa_verify.h"

#include <stdbool.h>
#include <stdint.h>

#include "errors.h"
#include "otbn_driver.h"

// RSA-3072 sizes.
#define RSA_3072_NUM_BYTES 384
#define RSA_3072_NUM_WORDS 96
#define SHA256_WORDS 8

// OTBN RSA-3072 mode constant (from OTBN run_rsa.s).
#define MODE_RSA_3072_MODEXP_F4 0x1BEu

// OTBN DMEM symbol offsets — these come from the generated header.
// We include it here to get the OTBN_ADDR_T_INIT macro and symbols.
#include "rsa_3072_app_otbn.h"

#define DMEM_MODE_OFFSET OTBN_ADDR_T_INIT(rsa_3072_app, mode)
#define DMEM_N_OFFSET OTBN_ADDR_T_INIT(rsa_3072_app, rsa_n)
#define DMEM_INOUT_OFFSET OTBN_ADDR_T_INIT(rsa_3072_app, inout)

// ---------------------------------------------------------------------------
// PKCS#1 v1.5 DigestInfo for SHA-256 (19 bytes, ASN.1 encoded)
// ---------------------------------------------------------------------------

// Expected OTBN words for the DigestInfo + separator region (words[8..12]).
// Derived from the big-endian DigestInfo:
//   30 31 30 0d 06 09 60 86 48 01 65 03 04 02 01 05 00 04 20
// Plus the 0x00 separator before DigestInfo.
static const uint32_t pkcs1_di_words[5] = {
    0x05000420u, // word[8]:  DI[15..18] = {0x05, 0x00, 0x04, 0x20}
    0x03040201u, // word[9]:  DI[11..14] = {0x03, 0x04, 0x02, 0x01}
    0x86480165u, // word[10]: DI[7..10]  = {0x86, 0x48, 0x01, 0x65}
    0x0D060960u, // word[11]: DI[3..6]   = {0x0D, 0x06, 0x09, 0x60}
    0x00303130u, // word[12]: {0x00(sep), DI[0..2]} = {0x00, 0x30, 0x31, 0x30}
};

// Expected value for the header word (word[95]).
#define PKCS1_HEADER_WORD 0x0001FFFFu

// ---------------------------------------------------------------------------
// Byte-to-OTBN-word conversion helpers
// ---------------------------------------------------------------------------

// Convert 384 big-endian bytes to 96 OTBN words (little-endian word order).
// Each OTBN word[i] = (src[383-4i-3] << 24) | (src[383-4i-2] << 16) |
//                      (src[383-4i-1] << 8)  | src[383-4i]
static void bytes_to_otbn_words(const uint8_t *src, uint32_t *dst) {
    for (int i = 0; i < RSA_3072_NUM_WORDS; ++i) {
        int base = RSA_3072_NUM_BYTES - 4 - i * 4;
        dst[i] = ((uint32_t)src[base] << 24) | ((uint32_t)src[base + 1] << 16) |
                 ((uint32_t)src[base + 2] << 8) | ((uint32_t)src[base + 3]);
    }
}

// Convert 32 SHA-256 digest bytes to 8 OTBN hash words.
// OTBN word[i] corresponds to digest bytes [(7-i)*4 .. (7-i)*4+3] in
// big-endian per-word format.
static void digest_to_otbn_words(const uint8_t *digest, uint32_t *dst) {
    for (int i = 0; i < SHA256_WORDS; ++i) {
        int base = (SHA256_WORDS - 1 - i) * 4;
        dst[i] = ((uint32_t)digest[base] << 24) | ((uint32_t)digest[base + 1] << 16) |
                 ((uint32_t)digest[base + 2] << 8) | ((uint32_t)digest[base + 3]);
    }
}

// ---------------------------------------------------------------------------
// PKCS#1 v1.5 padding verification (constant-time)
// ---------------------------------------------------------------------------

// Verify the OTBN modexp result matches expected PKCS#1 v1.5 structure.
// Returns 0 if valid, non-zero if invalid.
static int verify_pkcs1_v15(const uint32_t *result, const uint8_t *digest) {
    volatile uint32_t diff = 0;

    // 1. Compare hash words (words[0..7]).
    uint32_t expected_hash[SHA256_WORDS];
    digest_to_otbn_words(digest, expected_hash);
    for (int i = 0; i < SHA256_WORDS; ++i) {
        diff |= result[i] ^ expected_hash[i];
    }

    // 2. Compare DigestInfo + separator (words[8..12]).
    for (int i = 0; i < 5; ++i) {
        diff |= result[8 + i] ^ pkcs1_di_words[i];
    }

    // 3. Verify padding (words[13..94] must all be 0xFFFFFFFF).
    for (int i = 13; i < 95; ++i) {
        diff |= result[i] ^ 0xFFFFFFFFu;
    }

    // 4. Verify header word (word[95] = 0x0001FFFF).
    diff |= result[95] ^ PKCS1_HEADER_WORD;

    return (diff != 0) ? -1 : 0;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int rsa_3072_verify(const uint8_t *digest, const uint8_t *signature, const uint8_t *modulus) {
    int rc;

    report_status(STATUS_TYPE_DEBUG, SEP_MSG_CRYPTO_INIT_CHECK);

    // 1. Initialize OTBN.
    rc = otbn_init();
    if (rc != OTBN_OK) {
        simputs("RSA_OTBN_INIT_FAIL\n");
        return rc;
    }

    // 2. Load RSA-3072 application.
    rc = otbn_load_rsa_app();
    if (rc != OTBN_OK) {
        simputs("RSA_OTBN_LOAD_FAIL\n");
        return rc;
    }

    // 3. Convert modulus and signature from big-endian bytes to OTBN words.
    uint32_t n_words[RSA_3072_NUM_WORDS];
    uint32_t sig_words[RSA_3072_NUM_WORDS];
    bytes_to_otbn_words(modulus, n_words);
    bytes_to_otbn_words(signature, sig_words);

    // 4. Write inputs to OTBN DMEM.
    otbn_dmem_write(DMEM_N_OFFSET, n_words, RSA_3072_NUM_WORDS);
    otbn_dmem_write(DMEM_INOUT_OFFSET, sig_words, RSA_3072_NUM_WORDS);
    {
        uint32_t mode = MODE_RSA_3072_MODEXP_F4;
        otbn_dmem_write(DMEM_MODE_OFFSET, &mode, 1);
    }

    // 5. Execute modular exponentiation.
    simputs("RSA_EXEC\n");
    rc = otbn_execute();
    if (rc != OTBN_OK) {
        simputs("RSA_EXEC_FAIL\n");
        return rc;
    }

    // 6. Read result from OTBN DMEM.
    uint32_t result[RSA_3072_NUM_WORDS];
    otbn_dmem_read(DMEM_INOUT_OFFSET, result, RSA_3072_NUM_WORDS);

    // 7. The result shares `inout` with the signature, so a modexp that did not
    //    happen leaves the caller's own signature bytes in `result`, and a
    //    signature authored as a well-formed PKCS#1 v1.5 block would verify
    //    against itself. sig^e mod n cannot equal sig for a value that also
    //    parses as that block, so an unchanged buffer means no modexp ran.
    //    otbn_execute() already rejects a command that never started; this is
    //    the same conclusion drawn from the data rather than from the block.
    //
    //    Both operands are public, so the fold is not for secrecy. It is one
    //    exit instead of a return per word, leaving no early branch for a fault
    //    to skip.
    uint32_t diff = 0;
    for (int i = 0; i < RSA_3072_NUM_WORDS; ++i) {
        diff |= result[i] ^ sig_words[i];
    }
    if (diff == 0u) {
        simputs("RSA_INOUT_UNCHANGED\n");
        return -1;
    }

    // 8. Verify PKCS#1 v1.5 padding and digest match.
    rc = verify_pkcs1_v15(result, digest);
    if (rc != 0) {
        simputs("RSA_PKCS1_FAIL\n");
        return -1;
    }

    simputs("RSA_VERIFY_OK\n");
    return 0;
}
