// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP HMAC (OpenTitan HMAC engine) firmware helpers, SHA-256 mode. Header-only.
// Addresses and field masks come from generated sep_addr.h / hmac.h (via sep.h).
// Do not alias those symbols. The encodings below are SW contracts PeakRDL
// does not emit (digest_size / key_length / ERR_CODE tables).

#ifndef SEP_HMAC_H
#define SEP_HMAC_H

#include <stdint.h>

#include "sep.h"

/*
 * CFG.digest_size / CFG.key_length field encodings (OpenTitan hmac.hjson).
 * Use with PeakRDL unions: cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256.
 */
#define SEP_HMAC_DIGEST_SIZE_SHA2_256 ((uint32_t)0x1u)
#define SEP_HMAC_DIGEST_SIZE_SHA2_384 ((uint32_t)0x2u)
#define SEP_HMAC_DIGEST_SIZE_SHA2_512 ((uint32_t)0x4u)
#define SEP_HMAC_DIGEST_SIZE_SHA2_NONE ((uint32_t)0x8u)

#define SEP_HMAC_KEY_LENGTH_128 ((uint32_t)0x01u)
#define SEP_HMAC_KEY_LENGTH_256 ((uint32_t)0x02u)
#define SEP_HMAC_KEY_LENGTH_384 ((uint32_t)0x04u)
#define SEP_HMAC_KEY_LENGTH_512 ((uint32_t)0x08u)
#define SEP_HMAC_KEY_LENGTH_1024 ((uint32_t)0x10u)
#define SEP_HMAC_KEY_LENGTH_NONE ((uint32_t)0x20u)

/*
 * ERR_CODE encodings (OT HMAC Programmer's Guide / SW error table).
 * DV fixed-vector table — not sampled from DUT RTL under test.
 */
#define SEP_HMAC_ERR_NO_ERROR ((uint32_t)0x0u)
#define SEP_HMAC_ERR_SW_PUSH_MSG_WHEN_SHA_DISABLED ((uint32_t)0x1u) /* unused */
#define SEP_HMAC_ERR_SW_HASH_START_WHEN_SHA_DISABLED ((uint32_t)0x2u)
#define SEP_HMAC_ERR_SW_UPDATE_SECRET_KEY_IN_PROCESS ((uint32_t)0x3u)
#define SEP_HMAC_ERR_SW_HASH_START_WHEN_ACTIVE ((uint32_t)0x4u)
#define SEP_HMAC_ERR_SW_PUSH_MSG_WHEN_DISALLOWED ((uint32_t)0x5u)

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
// 2 on a nonzero HMAC ERR_CODE, 3 if the done status did not RW1C-clear,
// 4 if the done status did not still read set on a second read after the poll.
static inline int sep_hmac_sha256(const uint8_t *msg, uint32_t len, uint32_t digest_out[8]) {
    uint32_t cfg = HMAC__CFG__SHA_EN_bm | HMAC__CFG__DIGEST_SWAP_bm |
                   (SEP_HMAC_DIGEST_SIZE_SHA2_256 << HMAC__CFG__DIGEST_SIZE_bp);
    sep_hmac_wr(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg);
    sep_hmac_wr(SEP_TOP_HMAC_CMD_BASE_ADDR, HMAC__CMD__HASH_START_bm);

    volatile uint8_t *fifo = (volatile uint8_t *)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    for (uint32_t i = 0; i < len; i++) {
        int t = SEP_HMAC_TIMEOUT;
        while ((sep_hmac_rd(SEP_TOP_HMAC_STATUS_BASE_ADDR) & HMAC__STATUS__FIFO_FULL_bm) &&
               (t-- > 0)) {
        }
        if (t <= 0) {
            return 1;
        }
        *fifo = msg[i];
        __asm__ volatile("fence" ::: "memory");
    }

    sep_hmac_wr(SEP_TOP_HMAC_CMD_BASE_ADDR, HMAC__CMD__HASH_PROCESS_bm);

    int t = SEP_HMAC_TIMEOUT;
    while (t-- > 0) {
        if (sep_hmac_rd(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR) & HMAC__INTR_STATE__HMAC_DONE_bm) {
            break;
        }
    }
    if (t <= 0) {
        return 1;
    }
    // A read has no side effect on the done event, so it must still be set here.
    // That rules out a bit that clears on read or drops by itself, and credits
    // the clear below to the write-one.
    if (!(sep_hmac_rd(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR) & HMAC__INTR_STATE__HMAC_DONE_bm)) {
        return 4;
    }
    sep_hmac_wr(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, HMAC__INTR_STATE__HMAC_DONE_bm);
    if (sep_hmac_rd(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR) & HMAC__INTR_STATE__HMAC_DONE_bm) {
        return 3;
    }

    for (int i = 0; i < 8; i++) {
        digest_out[i] = sep_hmac_rd(SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
    }
    if (sep_hmac_rd(SEP_TOP_HMAC_ERR_CODE_BASE_ADDR) != 0) {
        return 2;
    }
    return 0;
}

#endif // SEP_HMAC_H
