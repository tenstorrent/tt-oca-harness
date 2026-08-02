/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SHA-256 Test Vectors
 *
 * Standard test vectors from NIST FIPS 180-4 and CAVP.
 * All digests are verified against OpenSSL output.
 */

#ifndef SHA256_VECTORS_H
#define SHA256_VECTORS_H

#include <stdint.h>
#include <stddef.h>

/* Test vector structure */
struct sha256_test_vector {
    const char *name;
    const uint8_t *message;
    size_t message_len;
    const uint8_t expected_digest[32];
};

/*
 * Vector 2: "abc" (NIST example)
 * echo -n "abc" | openssl dgst -sha256
 */
static const uint8_t sha256_vec2_msg[] = {'a', 'b', 'c'};

/*
 * Vector 3: 448 bits (56 bytes) - NIST example
 * "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
 */
static const uint8_t sha256_vec3_msg[] = {
    'a', 'b', 'c', 'd', 'b', 'c', 'd', 'e', 'c', 'd', 'e', 'f', 'd', 'e', 'f', 'g', 'e', 'f', 'g',
    'h', 'f', 'g', 'h', 'i', 'g', 'h', 'i', 'j', 'h', 'i', 'j', 'k', 'i', 'j', 'k', 'l', 'j', 'k',
    'l', 'm', 'k', 'l', 'm', 'n', 'l', 'm', 'n', 'o', 'm', 'n', 'o', 'p', 'n', 'o', 'p', 'q'};

/*
 * Vector 4: Exactly 64 bytes (one full block)
 * "abcdefghijklmnopqrstuvwxyz012345abcdefghijklmnopqrstuvwxyz012345"
 */
static const uint8_t sha256_vec4_msg[] = {
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p',
    'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', '0', '1', '2', '3', '4', '5',
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p',
    'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', '0', '1', '2', '3', '4', '5'};

/*
 * Vector 5: 55 bytes (padding boundary - single padding block)
 * "1234567890123456789012345678901234567890123456789012345"
 */
static const uint8_t sha256_vec5_msg[] = {
    '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '1', '2', '3', '4', '5', '6', '7', '8',
    '9', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '1', '2', '3', '4', '5'};

/*
 * Vector 6: Single byte
 * echo -n "a" | openssl dgst -sha256
 */
static const uint8_t sha256_vec6_msg[] = {'a'};

/*
 * Vector 7: 112 bytes (multi-block requiring 2 blocks)
 */
static const uint8_t sha256_vec7_msg[] = {
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'c', 'd', 'e',
    'f', 'g', 'h', 'i', 'j', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'e', 'f', 'g', 'h', 'i', 'j',
    'k', 'l', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'h',
    'i', 'j', 'k', 'l', 'm', 'n', 'o', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'j', 'k', 'l', 'm',
    'n', 'o', 'p', 'q', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 'l', 'm', 'n', 'o', 'p', 'q', 'r',
    's', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u'};

/* Array of all test vectors for iteration */
static const struct sha256_test_vector sha256_test_vectors[] = {
    {"empty string", NULL, 0, {0xe3, 0xb0, 0xc4, 0x42, 0x98, 0xfc, 0x1c, 0x14, 0x9a, 0xfb, 0xf4,
                               0xc8, 0x99, 0x6f, 0xb9, 0x24, 0x27, 0xae, 0x41, 0xe4, 0x64, 0x9b,
                               0x93, 0x4c, 0xa4, 0x95, 0x99, 0x1b, 0x78, 0x52, 0xb8, 0x55}},
    {"abc (NIST)",
     sha256_vec2_msg,
     sizeof(sha256_vec2_msg),
     {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40,
      0xde, 0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17,
      0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad}},
    {"56 bytes (448 bits)",
     sha256_vec3_msg,
     sizeof(sha256_vec3_msg),
     {0x24, 0x8d, 0x6a, 0x61, 0xd2, 0x06, 0x38, 0xb8, 0xe5, 0xc0, 0x26,
      0x93, 0x0c, 0x3e, 0x60, 0x39, 0xa3, 0x3c, 0xe4, 0x59, 0x64, 0xff,
      0x21, 0x67, 0xf6, 0xec, 0xed, 0xd4, 0x19, 0xdb, 0x06, 0xc1}},
    {"64 bytes (one block)",
     sha256_vec4_msg,
     sizeof(sha256_vec4_msg),
     {0xa5, 0x35, 0x1f, 0x87, 0xe6, 0x5c, 0xab, 0x73, 0x95, 0x07, 0xb6,
      0x34, 0x0c, 0xff, 0xb4, 0x94, 0x5b, 0x17, 0x03, 0xd6, 0x79, 0xca,
      0x55, 0xb5, 0x15, 0xd2, 0x9e, 0xb2, 0x67, 0x1b, 0xe6, 0xaf}},
    {"55 bytes (padding boundary)",
     sha256_vec5_msg,
     sizeof(sha256_vec5_msg),
     {0x03, 0xc3, 0xa7, 0x0e, 0x99, 0xed, 0x5e, 0xec, 0xcd, 0x80, 0xf7,
      0x37, 0x71, 0xfc, 0xf1, 0xec, 0xe6, 0x43, 0xd9, 0x39, 0xd9, 0xec,
      0xc7, 0x6f, 0x25, 0x54, 0x4b, 0x02, 0x33, 0xf7, 0x08, 0xe9}},
    {"single byte",
     sha256_vec6_msg,
     sizeof(sha256_vec6_msg),
     {0xca, 0x97, 0x81, 0x12, 0xca, 0x1b, 0xbd, 0xca, 0xfa, 0xc2, 0x31,
      0xb3, 0x9a, 0x23, 0xdc, 0x4d, 0xa7, 0x86, 0xef, 0xf8, 0x14, 0x7c,
      0x4e, 0x72, 0xb9, 0x80, 0x77, 0x85, 0xaf, 0xee, 0x48, 0xbb}},
    {"112 bytes (multi-block)",
     sha256_vec7_msg,
     sizeof(sha256_vec7_msg),
     {0xcf, 0x5b, 0x16, 0xa7, 0x78, 0xaf, 0x83, 0x80, 0x03, 0x6c, 0xe5,
      0x9e, 0x7b, 0x04, 0x92, 0x37, 0x0b, 0x24, 0x9b, 0x11, 0xe8, 0xf0,
      0x7a, 0x51, 0xaf, 0xac, 0x45, 0x03, 0x7a, 0xfe, 0xe9, 0xd1}},
};

#define SHA256_NUM_VECTORS (sizeof(sha256_test_vectors) / sizeof(sha256_test_vectors[0]))

#endif /* SHA256_VECTORS_H */
