// ROM-embedded public key digests for secure boot.
//
// Each entry is the SHA-256 digest of the RSA-3072 modulus (384 bytes, big-endian).
//
// Test key (slot 0, dev0):
//   Source: tools/tt-boot-manifest/tests/signing_keys/rsa_private_key.dev0.pem (submodule)
//   Computed: SHA-256(modulus_3072bit_big_endian) → 32 bytes
//
// Production builds MUST replace this file with real key digests.
// Use tools/generate_key_digests.py to regenerate from PEM files.

#include "key_digests.h"

// SHA-256 of dev0 RSA-3072 modulus (from rsa_private_key.dev0.pem).
static const uint8_t digest_dev0[SHA256_DIGEST_SIZE_BYTES] = {
    0x46, 0x76, 0xd0, 0x23, 0x73, 0x6b, 0x5e, 0xbd, 0x51, 0x31, 0xf7, 0x5b, 0x06, 0x2a, 0x35, 0x5e,
    0x9a, 0xe1, 0x79, 0x0e, 0x80, 0xc8, 0x72, 0xb5, 0xee, 0x9b, 0x0c, 0x1f, 0xff, 0x04, 0xc3, 0xe3,
};

public_key_info_t public_key_digests[NUM_PUBLIC_KEY_DIGESTS] = {
    {.digest = digest_dev0}, // slot 0: dev0 (test key)
    {.digest = (void *)0},   // slot 1: dev1
    {.digest = (void *)0},   // slot 2: prod0
    {.digest = (void *)0},   // slot 3: prod1
    {.digest = (void *)0},   // slot 4: prod2
    {.digest = (void *)0},   // slot 5: prod3
};
