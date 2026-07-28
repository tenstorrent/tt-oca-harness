// SPDX-License-Identifier: Apache-2.0
//
// SEP HMAC (OpenTitan HMAC engine) firmware driver, SHA-256 mode. Header-only.
// The engine is on the SEP crypto fabric at 0x1091_1000 (CSR clock always on at
// reset). This driver runs it as a plain SHA-256 hash (hmac_en=0, sha_en=1):
// configure, push the message bytes through the byte-addressable MSG FIFO,
// hash_process, poll the done status, and read the 256-bit digest.
//
// DIGEST_SWAP=1 makes the digest CSRs read back so that an 8x uint32 read,
// compared byte-wise (memcmp) to a standard big-endian SHA-256 byte array,
// matches -- the same convention the dma_hash test uses against sha256.c.

#ifndef SEP_HMAC_H
#define SEP_HMAC_H

#include <stdint.h>

#define SEP_HMAC_BASE 0x10911000u
#define SEP_HMAC_INTR_STATE (SEP_HMAC_BASE + 0x000)
#define SEP_HMAC_CFG (SEP_HMAC_BASE + 0x010)
#define SEP_HMAC_CMD (SEP_HMAC_BASE + 0x014)
#define SEP_HMAC_STATUS (SEP_HMAC_BASE + 0x018)
#define SEP_HMAC_ERR_CODE (SEP_HMAC_BASE + 0x01C)
#define SEP_HMAC_DIGEST_0 (SEP_HMAC_BASE + 0x0A4)
#define SEP_HMAC_MSG_FIFO 0x10912000u

// CFG fields.
#define SEP_HMAC_CFG_SHA_EN (1u << 1)
#define SEP_HMAC_CFG_DIGEST_SWAP (1u << 3)
#define SEP_HMAC_CFG_DIGEST_SHA256 (1u << 5) // digest_size[8:5] = 1 (SHA2_256)
// CMD fields.
#define SEP_HMAC_CMD_HASH_START (1u << 0)
#define SEP_HMAC_CMD_HASH_PROCESS (1u << 1)
// STATUS / INTR_STATE bits.
#define SEP_HMAC_STATUS_IDLE (1u << 0)
#define SEP_HMAC_STATUS_FIFO_FULL (1u << 2)
#define SEP_HMAC_INTR_DONE (1u << 0)

#define SEP_HMAC_TIMEOUT 1000000

static inline uint32_t sep_hmac_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}
static inline void sep_hmac_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// SHA-256 over `msg[0..len)`. Returns 0 on success (digest in digest_out[8],
// byte-compatible with a standard SHA-256 byte array), 1 on done-timeout,
// 2 on a nonzero HMAC ERR_CODE, 3 if the done status did not RW1C-clear.
static inline int sep_hmac_sha256(const uint8_t *msg, uint32_t len, uint32_t digest_out[8]) {
    sep_hmac_wr(SEP_HMAC_CFG,
                SEP_HMAC_CFG_SHA_EN | SEP_HMAC_CFG_DIGEST_SWAP | SEP_HMAC_CFG_DIGEST_SHA256);
    sep_hmac_wr(SEP_HMAC_CMD, SEP_HMAC_CMD_HASH_START);

    volatile uint8_t *fifo = (volatile uint8_t *)SEP_HMAC_MSG_FIFO;
    for (uint32_t i = 0; i < len; i++) {
        int t = SEP_HMAC_TIMEOUT;
        while ((sep_hmac_rd(SEP_HMAC_STATUS) & SEP_HMAC_STATUS_FIFO_FULL) && (t-- > 0)) {
        }
        if (t <= 0) {
            return 1;
        }
        *fifo = msg[i];
        __asm__ volatile("fence" ::: "memory");
    }

    sep_hmac_wr(SEP_HMAC_CMD, SEP_HMAC_CMD_HASH_PROCESS);

    int t = SEP_HMAC_TIMEOUT;
    while (t-- > 0) {
        if (sep_hmac_rd(SEP_HMAC_INTR_STATE) & SEP_HMAC_INTR_DONE) {
            break;
        }
    }
    if (t <= 0) {
        return 1;
    }
    sep_hmac_wr(SEP_HMAC_INTR_STATE, SEP_HMAC_INTR_DONE); // W1C the done event
    // RW1C contract (AGENTS.md §7): the done status must read back cleared.
    if (sep_hmac_rd(SEP_HMAC_INTR_STATE) & SEP_HMAC_INTR_DONE) {
        return 3;
    }

    for (int i = 0; i < 8; i++) {
        digest_out[i] = sep_hmac_rd(SEP_HMAC_DIGEST_0 + i * 4);
    }
    if (sep_hmac_rd(SEP_HMAC_ERR_CODE) != 0) {
        return 2;
    }
    return 0;
}

#endif // SEP_HMAC_H
