// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP KMAC (OpenTitan KMAC engine) firmware helpers, KMAC128/cSHAKE with
// SOFTWARE entropy. Header-only.
// Addresses and field masks come from generated sep_addr.h / kmac.h (via sep.h).
// Do not alias those symbols. The encodings below are SW contracts PeakRDL
// does not emit (sha3_mode / kstrength / entropy_mode / CMD / ERR_CODE).
//
// Entropy: set entropy_ready first (StSwSeedWait), then write ENTROPY_SEED
// six times. SW mode is self-contained and does not wait on EDN.

#ifndef SEP_KMAC_H
#define SEP_KMAC_H

#include <stdint.h>

#include "sep.h"
#include "och_sep_common.h"

/* OT KMAC STATE window: share0 then share1; size from sep_addr.h. */
#define SEP_KMAC_STATE_SHARE1_OFFSET (SEP_TOP_KMAC_STATE_SIZE / 2u)

#define SEP_KMAC_NUM_SEED_WORDS 6
#define SEP_KMAC_TIMEOUT 1000000

/*
 * CFG_SHADOWED field encodings (OT sha3_mode_e / kstrength / entropy_mode).
 * Use with PeakRDL unions: cfg.f.mode = SEP_KMAC_MODE_CSHAKE.
 */
#define SEP_KMAC_MODE_SHA3 ((uint32_t)0x0u)     /* 2'b00 */
#define SEP_KMAC_MODE_RESERVED ((uint32_t)0x1u) /* 2'b01 reserved; used as a mismatch value */
#define SEP_KMAC_MODE_SHAKE ((uint32_t)0x2u)    /* 2'b10 */
#define SEP_KMAC_MODE_CSHAKE ((uint32_t)0x3u)   /* 2'b11 */

#define SEP_KMAC_KSTRENGTH_L128 ((uint32_t)0x0u)
#define SEP_KMAC_KSTRENGTH_L224 ((uint32_t)0x1u)
#define SEP_KMAC_KSTRENGTH_L256 ((uint32_t)0x2u)
#define SEP_KMAC_KSTRENGTH_L384 ((uint32_t)0x3u)
#define SEP_KMAC_KSTRENGTH_L512 ((uint32_t)0x4u)

#define SEP_KMAC_ENTROPY_MODE_NONE ((uint32_t)0x0u)
#define SEP_KMAC_ENTROPY_MODE_EDN ((uint32_t)0x1u)
#define SEP_KMAC_ENTROPY_MODE_SW ((uint32_t)0x2u)

/* Sparse CMD.CMD encodings (OT KMAC Programmer's Guide / generated kmac.adoc). */
#define SEP_KMAC_CMD_START 29u
#define SEP_KMAC_CMD_PROCESS 46u
#define SEP_KMAC_CMD_MANUAL_RUN 49u
#define SEP_KMAC_CMD_DONE 22u

/*
 * ERR_CODE: bits [31:24] = code byte, [23:0] = info (OT KMAC Programmer's Guide).
 */
#define SEP_KMAC_ERR_CODE_SHIFT ((uint32_t)24u)
#define SEP_KMAC_ERR_PACK(code) (((uint32_t)(code)) << SEP_KMAC_ERR_CODE_SHIFT)
#define SEP_KMAC_ERR_CODE_BYTE(err_word) (((uint32_t)(err_word)) >> SEP_KMAC_ERR_CODE_SHIFT)

#define SEP_KMAC_ERR_NONE ((uint32_t)0x00u)
#define SEP_KMAC_ERR_KEY_NOT_VALID ((uint32_t)0x01u)
#define SEP_KMAC_ERR_SW_PUSHED_MSG_FIFO ((uint32_t)0x02u)
#define SEP_KMAC_ERR_SW_ISSUED_CMD_IN_APP_ACTIVE ((uint32_t)0x03u)
#define SEP_KMAC_ERR_WAIT_TIMER_EXPIRED ((uint32_t)0x04u)
#define SEP_KMAC_ERR_INCORRECT_ENTROPY_MODE ((uint32_t)0x05u)
#define SEP_KMAC_ERR_UNEXPECTED_MODE_STRENGTH ((uint32_t)0x06u)
#define SEP_KMAC_ERR_INCORRECT_FUNCTION_NAME ((uint32_t)0x07u)
#define SEP_KMAC_ERR_SW_CMD_SEQUENCE ((uint32_t)0x08u)
#define SEP_KMAC_ERR_SW_HASHING_WITHOUT_ENTROPY_READY ((uint32_t)0x09u)
#define SEP_KMAC_ERR_UNEXPECTED_LCA_ESCALATION ((uint32_t)0x0Au)

static inline uint32_t sep_kmac_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}
static inline void sep_kmac_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// CFG_SHADOWED needs the same value written twice to commit the shadow copy.
static inline void sep_kmac_cfg_write(uint32_t value) {
    sep_kmac_wr(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, value);
    sep_kmac_wr(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, value);
}

// Run a KMAC128 over the 4-byte message "test" with a zero key and the "KMAC"
// cSHAKE prefix, using software entropy. Returns 0 on success (the unmasked
// digest share0^share1 is written to digest_out[8]), 1 on idle-timeout,
// 2 on done-timeout, 3 on a nonzero KMAC ERR_CODE, 4 if the done status did not
// RW1C-clear.
static inline int sep_kmac128_sw_smoke(uint32_t digest_out[8]) {
    int t = SEP_KMAC_TIMEOUT;
    while ((t-- > 0) &&
           !(sep_kmac_rd(SEP_TOP_KMAC_STATUS_BASE_ADDR) & KMAC__STATUS__SHA3_IDLE_bm)) {
    }
    if (t <= 0) {
        return 1;
    }

    const uint32_t base_cfg = KMAC__CFG_SHADOWED__KMAC_EN_bm |
                              (SEP_KMAC_MODE_CSHAKE << KMAC__CFG_SHADOWED__MODE_bp) |
                              (SEP_KMAC_ENTROPY_MODE_SW << KMAC__CFG_SHADOWED__ENTROPY_MODE_bp);
    sep_kmac_cfg_write(base_cfg);
    sep_kmac_cfg_write(base_cfg | KMAC__CFG_SHADOWED__ENTROPY_READY_bm);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        sep_kmac_wr(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEFu + (uint32_t)i);
    }

    sep_kmac_wr(SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, 0u); // Key128
    for (int i = 0; i < 4; i++) {
        sep_kmac_wr(SEP_TOP_KMAC_KEY_SHARE0_BASE_ADDR(i), 0u);
        sep_kmac_wr(SEP_TOP_KMAC_KEY_SHARE1_BASE_ADDR(i), 0u);
    }
    sep_kmac_wr(SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x4D4B2001u);
    sep_kmac_wr(SEP_TOP_KMAC_PREFIX_BASE_ADDR(1), 0x00004341u);
    for (int i = 2; i < 11; i++) {
        sep_kmac_wr(SEP_TOP_KMAC_PREFIX_BASE_ADDR(i), 0u);
    }

    sep_kmac_wr(SEP_TOP_KMAC_CMD_BASE_ADDR, SEP_KMAC_CMD_START);
    sep_kmac_wr(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x74736574u); // "test", little-endian
    sep_kmac_wr(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, 0x00020001u); // right_encode(256)
    sep_kmac_wr(SEP_TOP_KMAC_CMD_BASE_ADDR, SEP_KMAC_CMD_PROCESS);

    t = SEP_KMAC_TIMEOUT;
    while (t-- > 0) {
        if (sep_kmac_rd(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & KMAC__INTR_STATE__KMAC_DONE_bm) {
            break;
        }
    }
    if (t <= 0) {
        return 2;
    }
    sep_kmac_wr(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
    int rw1c_fail =
        (sep_kmac_rd(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & KMAC__INTR_STATE__KMAC_DONE_bm) ? 1
                                                                                              : 0;

    for (int i = 0; i < 8; i++) {
        uint32_t s0 = sep_kmac_rd(SEP_TOP_KMAC_STATE_BASE_ADDR + i * 4);
        uint32_t s1 =
            sep_kmac_rd(SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + i * 4);
        digest_out[i] = s0 ^ s1;
    }

    int err = (sep_kmac_rd(SEP_TOP_KMAC_ERR_CODE_BASE_ADDR) != 0);
    sep_kmac_wr(SEP_TOP_KMAC_CMD_BASE_ADDR, SEP_KMAC_CMD_DONE);
    if (rw1c_fail) {
        return 4;
    }
    return err ? 3 : 0;
}

#endif // SEP_KMAC_H
