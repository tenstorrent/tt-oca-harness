/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_hmac.c
 * @brief Software HMAC-SHA256 for Key Manager ROM firmware.
 */

#include <stdint.h>
#include <stddef.h>

#include "rom_hmac.h"
#include "rom_secutil.h"

/* Provided by rom_memcpy.c / rom_memset.c (libc-name aliases). */
void *memcpy(void *dest, const void *src, size_t n);
void *memset(void *dest, int c, size_t n);

/*
 * HMAC scratch contains masked key material and therefore lives in BSS rather
 * than in dead stack frames. The KM firmware is single-threaded, and each
 * inner/outer step scrubs the shared context before returning.
 */
static struct rom_sha256_ctx g_hmac_ctx;

/*
 * Compute one HMAC step: output = hash((key zero-padded ^ mask) || data).
 * Returns 0 on success; -1 if the hash failed, in which case output is zeroed.
 */
static int rom_hmac_sha256_step(uint8_t *output, uint8_t mask, const uint8_t *key, uint32_t key_len,
                                const uint8_t *data, uint32_t data_len) {
    struct rom_sha256_ctx *ctx = &g_hmac_ctx;
    uint8_t *key_pad = ctx->block;
    uint8_t *tmp;
    int ret;

    /* key_pad = key (zero-padded) ^ mask */
    memset(key_pad, (int)mask, ROM_SHA256_BLOCK_SIZE);
    for (uint32_t i = 0u; i < key_len; i++) key_pad[i] = (uint8_t)(key_pad[i] ^ key[i]);

    /* tmp = hash(key_pad || data) */
    rom_sha256_init_one_block(ctx, key_pad);
    rom_sha256_update(ctx, data, data_len);
    tmp = rom_sha256_final(ctx);

    if (tmp == NULL) {
        /* SHA failed (e.g. glitch-induced error flag): fail safe. */
        rom_secure_memzero(output, ROM_SHA256_DIGEST_SIZE);
        ret = -1;
    } else {
        memcpy(output, tmp, ROM_SHA256_DIGEST_SIZE);
        ret = 0;
    }

    /* Wipe the context: ctx.block held the masked key and ctx.buf the digest. */
    rom_secure_memzero(ctx, sizeof(*ctx));

    return ret;
}

int rom_hmac_sha256(uint8_t *output, const uint8_t *key, uint32_t key_len, const uint8_t *message,
                    uint32_t message_len) {
    if (output == NULL) return -1;

    /* Reject inconsistent pointer/length pairs and unsupported key sizes. */
    if (((key == NULL) && (key_len != 0u)) || ((message == NULL) && (message_len != 0u)) ||
        (key_len > (uint32_t)ROM_SHA256_BLOCK_SIZE) || (message_len > ROM_HMAC_MAX_MESSAGE_BYTES)) {
        rom_secure_memzero(output, ROM_SHA256_DIGEST_SIZE);
        return -1;
    }

    /*
     * i_key_pad = key (zero-padded) ^ 0x36
     * output    = hash(i_key_pad || message)   (output used as scratch)
     *
     * On inner-hash failure, output is already zeroed; abort so the outer
     * step cannot turn the failure into a valid-looking non-zero MAC.
     */
    if (rom_hmac_sha256_step(output, (uint8_t)0x36u, key, key_len, message, message_len) != 0) {
        return -1;
    }

    /*
     * o_key_pad = key (zero-padded) ^ 0x5c
     * output    = hash(o_key_pad || output)
     *
     * On failure the step zeroes output itself, so no handling is needed.
     */
    return rom_hmac_sha256_step(output, (uint8_t)0x5cu, key, key_len, output,
                                (uint32_t)ROM_SHA256_DIGEST_SIZE);
}
