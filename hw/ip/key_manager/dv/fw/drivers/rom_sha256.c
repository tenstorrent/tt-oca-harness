/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SHA-256 implementation for KM ROM firmware.
 *
 * Based on Olivier Gay's FIPS 180-2 SHA-256 code; original copyright/license
 * retained below.
 */

/*
 * FIPS 180-2 SHA-224/256/384/512 implementation
 * Last update: 02/02/2007
 * Issue date:  04/30/2005
 *
 * Copyright (C) 2005, 2007 Olivier Gay <olivier.gay@a3.epfl.ch>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. Neither the name of the project nor the names of its contributors
 *    may be used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE PROJECT AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE PROJECT OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

/* Copyright 2026 Tenstorrent Inc. */

#include <stdint.h>
#include <stddef.h>

#include "rom_sha256.h"

/* Provided by rom_memcpy.c / rom_memset.c (libc-name aliases). */
void *memcpy(void *dest, const void *src, size_t n);
void *memset(void *dest, int c, size_t n);

#define SHFR(x, n) ((x) >> (n))
#define ROTR(x, n) (((x) >> (n)) | ((x) << ((sizeof(x) << 3) - (n))))
#define CH(x, y, z) (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))

#define SHA256_F1(x) (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define SHA256_F2(x) (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SHA256_F3(x) (ROTR(x, 7) ^ ROTR(x, 18) ^ SHFR(x, 3))
#define SHA256_F4(x) (ROTR(x, 17) ^ ROTR(x, 19) ^ SHFR(x, 10))

#define UNPACK32(x, str) \
    do { \
        *((str) + 3) = (uint8_t)((x)); \
        *((str) + 2) = (uint8_t)((x) >> 8); \
        *((str) + 1) = (uint8_t)((x) >> 16); \
        *((str) + 0) = (uint8_t)((x) >> 24); \
    } while (0)

#define PACK32(str, x) \
    do { \
        *(x) = ((uint32_t) * ((str) + 3)) | ((uint32_t) * ((str) + 2) << 8) | \
               ((uint32_t) * ((str) + 1) << 16) | ((uint32_t) * ((str) + 0) << 24); \
    } while (0)

static const uint32_t sha256_h0[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
                                      0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};

static const uint32_t sha256_k[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u,
    0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu,
    0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu,
    0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
    0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u,
    0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u,
    0xc67178f2u};

void rom_sha256_init(struct rom_sha256_ctx *ctx) {
    for (int i = 0; i < 8; i++) ctx->h[i] = sha256_h0[i];

    ctx->len = 0u;
    ctx->tot_len = 0u;
    ctx->error = 0;
}

/* Note: this function requires a considerable amount of stack. */
static void rom_sha256_transform(struct rom_sha256_ctx *ctx, const uint8_t *message,
                                 unsigned int block_nb) {
    uint32_t w[64];
    uint32_t wv[8];
    uint32_t t1, t2;
    const uint8_t *sub_block;

    for (unsigned int i = 0u; i < block_nb; i++) {
        sub_block = message + (i << 6);

        for (unsigned int j = 0u; j < 16u; j++) PACK32(&sub_block[j << 2], &w[j]);

        for (unsigned int j = 16u; j < 64u; j++)
            w[j] = SHA256_F4(w[j - 2]) + w[j - 7] + SHA256_F3(w[j - 15]) + w[j - 16];

        for (unsigned int j = 0u; j < 8u; j++) wv[j] = ctx->h[j];

        for (unsigned int j = 0u; j < 64u; j++) {
            t1 = wv[7] + SHA256_F2(wv[4]) + CH(wv[4], wv[5], wv[6]) + sha256_k[j] + w[j];
            t2 = SHA256_F1(wv[0]) + MAJ(wv[0], wv[1], wv[2]);
            wv[7] = wv[6];
            wv[6] = wv[5];
            wv[5] = wv[4];
            wv[4] = wv[3] + t1;
            wv[3] = wv[2];
            wv[2] = wv[1];
            wv[1] = wv[0];
            wv[0] = t1 + t2;
        }

        for (unsigned int j = 0u; j < 8u; j++) ctx->h[j] += wv[j];
    }
}

void rom_sha256_update(struct rom_sha256_ctx *ctx, const uint8_t *data, uint32_t len) {
    unsigned int block_nb;
    unsigned int new_len, rem_len, tmp_len;
    const uint8_t *shifted_data;
    uint32_t bytes_to_add;

    /*
     * Validate ctx->len is within expected bounds. If corrupted (e.g. by a
     * glitch attack), fail safely.
     */
    if (ctx->len >= (uint32_t)ROM_SHA256_BLOCK_SIZE) {
        ctx->error = 1;
        return;
    }

    /*
     * Check for overflow in tot_len accumulation. We add up to
     * (len + SHA256_BLOCK_SIZE - 1) bytes to tot_len in this call, so headroom
     * for that worst case is required.
     */
    if (ctx->tot_len > UINT32_MAX - len - (uint32_t)(ROM_SHA256_BLOCK_SIZE - 1)) {
        ctx->error = 1;
        return;
    }

    tmp_len = (uint32_t)ROM_SHA256_BLOCK_SIZE - ctx->len;
    rem_len = len < tmp_len ? len : tmp_len;

    memcpy(&ctx->block[ctx->len], data, rem_len);

    /*
     * If the new data fits completely within the remaining space in the
     * current block, just buffer it. This check avoids a ctx->len + len
     * overflow.
     */
    if (len < (uint32_t)ROM_SHA256_BLOCK_SIZE - ctx->len) {
        ctx->len += len;
        return;
    }

    new_len = len - rem_len;
    block_nb = new_len / (uint32_t)ROM_SHA256_BLOCK_SIZE;

    shifted_data = data + rem_len;

    rom_sha256_transform(ctx, ctx->block, 1u);
    rom_sha256_transform(ctx, shifted_data, block_nb);

    rem_len = new_len % (uint32_t)ROM_SHA256_BLOCK_SIZE;

    /*
     * Copy the final partial block. (new_len - rem_len) gives the offset of
     * the leftover bytes after the complete blocks, avoiding the overflow the
     * original (block_nb << 6) offset could hit for large block_nb.
     */
    memcpy(ctx->block, &shifted_data[new_len - rem_len], rem_len);

    ctx->len = rem_len;

    /*
     * Update tot_len with the bytes processed through transform: 1 block from
     * ctx->block plus block_nb blocks from data.
     */
    bytes_to_add = (new_len - rem_len) + (uint32_t)ROM_SHA256_BLOCK_SIZE;
    ctx->tot_len += bytes_to_add;
}

/*
 * Specialized rom_sha256_init + rom_sha256_update that takes the first data
 * block (exactly ROM_SHA256_BLOCK_SIZE bytes) as input.
 */
void rom_sha256_init_one_block(struct rom_sha256_ctx *ctx, const uint8_t *data) {
    for (int i = 0; i < 8; i++) ctx->h[i] = sha256_h0[i];

    rom_sha256_transform(ctx, data, 1u);

    ctx->len = 0u;
    ctx->tot_len = (uint32_t)ROM_SHA256_BLOCK_SIZE;
    ctx->error = 0;
}

uint8_t *rom_sha256_final(struct rom_sha256_ctx *ctx) {
    unsigned int block_nb;
    unsigned int pm_len;
    uint32_t len_b;

    /* Propagate any error flagged during update. */
    if (ctx->error) {
        return NULL;
    }

    block_nb =
        1u + (((uint32_t)(ROM_SHA256_BLOCK_SIZE - 9) < (ctx->len % (uint32_t)ROM_SHA256_BLOCK_SIZE))
                  ? 1u
                  : 0u);

    len_b = (ctx->tot_len + ctx->len) << 3;
    pm_len = block_nb << 6;

    memset(ctx->block + ctx->len, 0, pm_len - ctx->len);
    ctx->block[ctx->len] = (uint8_t)0x80u;
    UNPACK32(len_b, ctx->block + pm_len - 4u);

    rom_sha256_transform(ctx, ctx->block, block_nb);

    for (unsigned int i = 0u; i < 8u; i++) UNPACK32(ctx->h[i], &ctx->buf[i << 2]);

    return ctx->buf;
}
