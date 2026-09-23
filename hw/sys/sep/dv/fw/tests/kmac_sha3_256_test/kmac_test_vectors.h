/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SHA3-256 known-answer vectors (NIST FIPS 202), big-endian digest words. */

#ifndef KMAC_TEST_VECTORS_H_
#define KMAC_TEST_VECTORS_H_

#include <stdint.h>

/* SHA3-256 of empty string
 * Message: (empty)
 * Digest:  a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a
 */
static const uint32_t sha3_256_empty_ref[8] = {0xa7ffc6f8, 0xbf1ed766, 0x51c14756, 0xa061d662,
                                               0xf580ff4d, 0xe43b49fa, 0x82d80a4b, 0x80f8434a};

/* SHA3-256 of "abc" (NIST short message test)
 * Message: 616263
 * Digest:  3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532
 */
static const uint32_t sha3_256_abc_ref[8] = {0x3a985da7, 0x4fe225b2, 0x045c172d, 0x6bd390bd,
                                             0x855f086e, 0x3e9d525b, 0x46bfe245, 0x11431532};

/* SHA3-256 of alphabet string (NIST test)
 * Message:
 * 6162636462636465636465666465666765666768666768696768696a68696a6b696a6b6c6a6b6c6d6b6c6d6e6c6d6e6f6d6e6f706e6f7071
 * Digest:  41c0dba2a9d6240849100376a8235e2c82e1b9998a999e21db32dd97496d3376
 */
static const uint32_t sha3_256_alphabet_ref[8] = {0x41c0dba2, 0xa9d62408, 0x49100376, 0xa8235e2c,
                                                  0x82e1b999, 0x8a999e21, 0xdb32dd97, 0x496d3376};

#endif // KMAC_TEST_VECTORS_H_
