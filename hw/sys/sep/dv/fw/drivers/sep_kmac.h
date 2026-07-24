// SPDX-License-Identifier: Apache-2.0
//
// SEP KMAC (OpenTitan KMAC engine) firmware driver, KMAC128/cSHAKE mode with
// SOFTWARE entropy. Header-only. The engine is on the SEP crypto fabric at
// 0x1091_3000 (CSR clock always on at reset).
//
// Entropy: KMAC's masking PRNG (a prim_trivium Bivium, 177-bit state) must be
// seeded before it will process. This driver uses SOFTWARE entropy mode
// (entropy_mode=SW) so NO EDN/ESRC bring-up is needed: set entropy_ready FIRST
// (the entropy FSM only enters StSwSeedWait, where it accepts seed words, after
// entropy_ready), THEN write ENTROPY_SEED 6 times (ceil(177/32)=6 partial-seed
// chunks -> seed_done -> rand_valid). This is the deliberate fix vs the OCAH
// kmac_test.c, which selects EDN mode (entropy_mode=0x1) yet writes a SW seed --
// that would block waiting for EDN; SW mode is self-contained and cannot hang on
// an unseeded EDN. cf. hw/ip/kmac/rtl/kmac_entropy.sv + vendor prim_trivium.sv.

#ifndef SEP_KMAC_H
#define SEP_KMAC_H

#include <stdint.h>

#define SEP_KMAC_BASE 0x10913000u
#define SEP_KMAC_INTR_STATE (SEP_KMAC_BASE + 0x000)
#define SEP_KMAC_CFG_REGWEN (SEP_KMAC_BASE + 0x010)
#define SEP_KMAC_CFG_SHADOWED (SEP_KMAC_BASE + 0x014)
#define SEP_KMAC_CMD (SEP_KMAC_BASE + 0x018)
#define SEP_KMAC_STATUS (SEP_KMAC_BASE + 0x01C)
#define SEP_KMAC_ENTROPY_SEED (SEP_KMAC_BASE + 0x02C)
#define SEP_KMAC_KEY_SHARE0_0 (SEP_KMAC_BASE + 0x030)
#define SEP_KMAC_KEY_SHARE1_0 (SEP_KMAC_BASE + 0x070)
#define SEP_KMAC_KEY_LEN (SEP_KMAC_BASE + 0x0B0)
#define SEP_KMAC_PREFIX_0 (SEP_KMAC_BASE + 0x0B4)
#define SEP_KMAC_ERR_CODE (SEP_KMAC_BASE + 0x0E0)
#define SEP_KMAC_STATE_MEM 0x10913400u // share0 @ +0x000, share1 @ +0x100
#define SEP_KMAC_MSG_FIFO 0x10913800u

// CFG_SHADOWED fields.
#define SEP_KMAC_CFG_KMAC_EN (1u << 0)
#define SEP_KMAC_CFG_KSTRENGTH_128 (0u << 1) // kstrength[3:1] = L128
#define SEP_KMAC_CFG_MODE_CSHAKE (2u << 4)   // mode[5:4] = cSHAKE
#define SEP_KMAC_CFG_ENTROPY_SW (2u << 16)   // entropy_mode[17:16] = SW
#define SEP_KMAC_CFG_ENTROPY_READY (1u << 24)
// STATUS / INTR / CMD.
#define SEP_KMAC_STATUS_SHA3_IDLE (1u << 0)
#define SEP_KMAC_INTR_DONE (1u << 0)
#define SEP_KMAC_CMD_START 29u
#define SEP_KMAC_CMD_PROCESS 46u
#define SEP_KMAC_CMD_DONE 22u

#define SEP_KMAC_NUM_SEED_WORDS 6
#define SEP_KMAC_TIMEOUT 1000000

static inline uint32_t sep_kmac_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}
static inline void sep_kmac_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// CFG_SHADOWED needs the same value written twice to commit the shadow copy.
static inline void sep_kmac_cfg_write(uint32_t value) {
    sep_kmac_wr(SEP_KMAC_CFG_SHADOWED, value);
    sep_kmac_wr(SEP_KMAC_CFG_SHADOWED, value);
}

// Run a KMAC128 over the 4-byte message "test" with a zero key and the "KMAC"
// cSHAKE prefix, using software entropy. Returns 0 on success (the unmasked
// digest share0^share1 is written to digest_out[8]), 1 on idle-timeout,
// 2 on done-timeout, 3 on a nonzero KMAC ERR_CODE, 4 if the done status did not
// RW1C-clear.
static inline int sep_kmac128_sw_smoke(uint32_t digest_out[8]) {
    int t = SEP_KMAC_TIMEOUT;
    while ((t-- > 0) && !(sep_kmac_rd(SEP_KMAC_STATUS) & SEP_KMAC_STATUS_SHA3_IDLE)) {
    }
    if (t <= 0) {
        return 1;
    }

    const uint32_t base_cfg = SEP_KMAC_CFG_KMAC_EN | SEP_KMAC_CFG_KSTRENGTH_128 |
                              SEP_KMAC_CFG_MODE_CSHAKE | SEP_KMAC_CFG_ENTROPY_SW;
    // entropy_ready=0 first, then set entropy_ready so the entropy FSM enters
    // StSwSeedWait, THEN feed the 6 software-seed words.
    sep_kmac_cfg_write(base_cfg);
    sep_kmac_cfg_write(base_cfg | SEP_KMAC_CFG_ENTROPY_READY);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        sep_kmac_wr(SEP_KMAC_ENTROPY_SEED, 0xDEADBEEFu + (uint32_t)i);
    }

    sep_kmac_wr(SEP_KMAC_KEY_LEN, 0u); // Key128
    for (int i = 0; i < 4; i++) {
        sep_kmac_wr(SEP_KMAC_KEY_SHARE0_0 + i * 4, 0u);
        sep_kmac_wr(SEP_KMAC_KEY_SHARE1_0 + i * 4, 0u);
    }
    // cSHAKE function-name prefix encode_string("KMAC").
    sep_kmac_wr(SEP_KMAC_PREFIX_0, 0x4D4B2001u);
    sep_kmac_wr(SEP_KMAC_PREFIX_0 + 4, 0x00004341u);
    for (int i = 2; i < 11; i++) {
        sep_kmac_wr(SEP_KMAC_PREFIX_0 + i * 4, 0u);
    }

    sep_kmac_wr(SEP_KMAC_CMD, SEP_KMAC_CMD_START);
    sep_kmac_wr(SEP_KMAC_MSG_FIFO, 0x74736574u); // "test", little-endian
    sep_kmac_wr(SEP_KMAC_MSG_FIFO, 0x00020001u); // right_encode(256)
    sep_kmac_wr(SEP_KMAC_CMD, SEP_KMAC_CMD_PROCESS);

    t = SEP_KMAC_TIMEOUT;
    while (t-- > 0) {
        if (sep_kmac_rd(SEP_KMAC_INTR_STATE) & SEP_KMAC_INTR_DONE) {
            break;
        }
    }
    if (t <= 0) {
        return 2;
    }
    sep_kmac_wr(SEP_KMAC_INTR_STATE, SEP_KMAC_INTR_DONE); // W1C the done event
    // RW1C contract (AGENTS.md §7): the done status must read back cleared.
    int rw1c_fail = (sep_kmac_rd(SEP_KMAC_INTR_STATE) & SEP_KMAC_INTR_DONE) ? 1 : 0;

    for (int i = 0; i < 8; i++) {
        uint32_t s0 = sep_kmac_rd(SEP_KMAC_STATE_MEM + i * 4);
        uint32_t s1 = sep_kmac_rd(SEP_KMAC_STATE_MEM + 0x100 + i * 4);
        digest_out[i] = s0 ^ s1;
    }

    int err = (sep_kmac_rd(SEP_KMAC_ERR_CODE) != 0);
    sep_kmac_wr(SEP_KMAC_CMD, SEP_KMAC_CMD_DONE);
    if (rw1c_fail) {
        return 4;
    }
    return err ? 3 : 0;
}

#endif // SEP_KMAC_H
