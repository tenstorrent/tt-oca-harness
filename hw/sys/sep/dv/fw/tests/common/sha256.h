/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

//
// SHA-256 software reference (public-domain implementation by Brad Conte,
// brad AT bradconte.com, "presented as is"). Used as the golden reference the
// dma_hash test compares the Secure-DMA inline-SHA hardware digest against.

#ifndef SEP_SHA256_H
#define SEP_SHA256_H

#include <stddef.h>

#define SHA256_BLOCK_SIZE 32 // SHA-256 outputs a 32-byte digest

typedef unsigned char BYTE; // 8-bit byte
typedef unsigned int WORD;  // 32-bit word

typedef struct {
    BYTE data[64];
    WORD datalen;
    unsigned long long bitlen;
    WORD state[8];
} SHA256_CTX;

void sha256_init(SHA256_CTX *ctx);
void sha256_update(SHA256_CTX *ctx, const BYTE data[], size_t len);
void sha256_final(SHA256_CTX *ctx, BYTE hash[]);

#endif // SEP_SHA256_H
