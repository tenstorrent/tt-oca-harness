/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Shared Adams Bridge (ML-DSA-87) helpers for SEP firmware tests.
 *
 * Register map taken from abr_reg.rdl (MLDSA block), at the SEP ABR aperture
 * documented in memory_map.adoc (same base as cocotb/env/sep_spec_tables.py
 * WINDOWS["ABR"]).
 * Completion model: Adams Bridge parks the sequencer at the op's end state
 * with STATUS.VALID asserted and does NOT auto-return to RESET, so completion
 * is detected via VALID and a zeroize is required between back-to-back
 * operations (see abr_zeroize()).
 */

#ifndef SEP_ABR_MLDSA_H
#define SEP_ABR_MLDSA_H

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"

/* ------------------------------------------------------------------------- */
/* Register map (offsets from abr_reg.rdl, MLDSA block)                      */
/* ------------------------------------------------------------------------- */
#define ABR_BASE 0x10940000u

#define ABR_MLDSA_NAME0 (ABR_BASE + 0x000u)
#define ABR_MLDSA_NAME1 (ABR_BASE + 0x004u)
#define ABR_MLDSA_VERSION0 (ABR_BASE + 0x008u)
#define ABR_MLDSA_VERSION1 (ABR_BASE + 0x00Cu)
#define ABR_MLDSA_CTRL (ABR_BASE + 0x010u)
#define ABR_MLDSA_STATUS (ABR_BASE + 0x014u)
#define ABR_MLDSA_ENTROPY (ABR_BASE + 0x018u)     /* 16 words */
#define ABR_MLDSA_SEED (ABR_BASE + 0x058u)        /*  8 words */
#define ABR_MLDSA_SIGN_RND (ABR_BASE + 0x078u)    /*  8 words */
#define ABR_MLDSA_MSG (ABR_BASE + 0x098u)         /* 16 words */
#define ABR_MLDSA_VERIFY_RES (ABR_BASE + 0x0D8u)  /* 16 words */
#define ABR_MLDSA_EXTERNAL_MU (ABR_BASE + 0x118u) /* 16 words (precomputed mu) */
#define ABR_MLDSA_PUBKEY (ABR_BASE + 0x1000u)     /* 648 words  (2592 B) */
#define ABR_MLDSA_SIGNATURE (ABR_BASE + 0x2000u)  /* 1157 words (4628 B) */
#define ABR_MLDSA_PRIVKEY_IN (ABR_BASE + 0x6000u) /* 1224 words, write-only (sk in) */

/*
 * Key-Vault seed read control (abr_reg.rdl kv_mldsa_seed_rd_ctrl @0x8000).
 * Writing READ_EN=1 tells abr_ctrl's kv_read_client to pull the ML-DSA seed
 * from the Key Vault (kv_read[0]) instead of the software-written MLDSA_SEED
 * register. In SEP this KV lane is served by sep_abr_kv_shim, which reconstructs
 * the seed from the KM-delivered XOR shares in abr_wrapper_key_reg. The launched
 * command is masked until the KV read completes (kv_mldsa_seed_ready).
 */
#define ABR_MLDSA_KV_RD_SEED_CTRL (ABR_BASE + 0x8000u)
#define ABR_KV_RD_SEED_READ_EN (1u << 0) /* bit0: initiate KV seed copy   */
#define ABR_KV_RD_SEED_ENTRY_SHIFT 1u    /* bits[5:1]: KV entry (shim NOP) */

/* Expected block identity: MLDSA_CORE_NAME = 64'h3837412D_44534D4C ("MLDSA-87"). */
#define ABR_MLDSA_NAME0_EXP 0x44534d4cu
#define ABR_MLDSA_NAME1_EXP 0x3837412du

/* CTRL[2:0] command field + modifier bits */
#define ABR_CMD_KEYGEN 0x1u
#define ABR_CMD_SIGN 0x2u
#define ABR_CMD_VERIFY 0x3u
#define ABR_CMD_KEYGEN_SIGN 0x4u
#define ABR_CTRL_ZEROIZE (1u << 3)
#define ABR_CTRL_EXTERNAL_MU (1u << 5) /* CTRL bit5: take precomputed mu from MLDSA_EXTERNAL_MU */

/* STATUS bits */
#define ABR_ST_READY (1u << 0)
#define ABR_ST_VALID (1u << 1)
#define ABR_ST_ERROR (1u << 3)

/* Field sizes (32-bit words) */
#define MLDSA_SEED_WORDS 8
#define MLDSA_ENTROPY_WORDS 16
#define MLDSA_SIGN_RND_WORDS 8
#define MLDSA_MSG_WORDS 16
#define MLDSA_CHASH_WORDS 16 /* c~ commitment = first 64 bytes of SIGNATURE */
#define MLDSA_PK_WORDS 648
#define MLDSA_SIG_WORDS 1157
#define MLDSA_EXTMU_WORDS 16
#define MLDSA_PRIVKEY_WORDS 1224

/* Generous poll budget; the testbench run timeout is the real backstop. */
#define ABR_POLL_TIMEOUT 2000000

/* ------------------------------------------------------------------------- */
/* Fixed software KAT inputs (any deterministic non-zero values work)        */
/* ------------------------------------------------------------------------- */
static const uint32_t k_seed[MLDSA_SEED_WORDS] = {0x00010203u, 0x04050607u, 0x08090a0bu,
                                                  0x0c0d0e0fu, 0x10111213u, 0x14151617u,
                                                  0x18191a1bu, 0x1c1d1e1fu};

static const uint32_t k_entropy[MLDSA_ENTROPY_WORDS] = {
    0xa5a5a5a5u, 0x5a5a5a5au, 0xdeadbeefu, 0xcafef00du, 0x01234567u, 0x89abcdefu,
    0xfedcba98u, 0x76543210u, 0x0f0f0f0fu, 0xf0f0f0f0u, 0x33333333u, 0xccccccccu,
    0xa5a5a5a5u, 0x5a5a5a5au, 0xdeadc0deu, 0xfeedfaceu};

static const uint32_t k_sign_rnd[MLDSA_SIGN_RND_WORDS] = {
    0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u /* deterministic (non-hedged) signing */
};

static const uint32_t k_msg[MLDSA_MSG_WORDS] = {
    0x41425220u, 0x4b415420u, 0x6d736720u, 0x76303031u, /* "ABR KAT msg v001" */
    0x11223344u, 0x55667788u, 0x99aabbccu, 0xddeeff00u, 0x0badf00du, 0x8badf00du,
    0xfaceb00cu, 0x1ceb00dau, 0x00000000u, 0x11111111u, 0x22222222u, 0x33333333u};

/* ------------------------------------------------------------------------- */
/* Helpers                                                                   */
/* ------------------------------------------------------------------------- */
static inline void abr_write_array(uintptr_t base, const uint32_t *src, int words) {
    for (int i = 0; i < words; i++) {
        WRITE_MEM_WORD(base, i, src[i]);
    }
}

static inline void abr_read_array(uintptr_t base, uint32_t *dst, int words) {
    for (int i = 0; i < words; i++) {
        dst[i] = READ_MEM_WORD(base, i);
    }
}

static inline int abr_wait_ready(void) {
    return poll_reg_timeout(ABR_MLDSA_STATUS, ABR_ST_READY, ABR_ST_READY, ABR_POLL_TIMEOUT);
}

static inline int abr_words_any_nonzero(const uint32_t *a, int n) {
    for (int i = 0; i < n; i++) {
        if (a[i] != 0u) {
            return 1;
        }
    }
    return 0;
}

static inline int abr_words_equal(const uint32_t *a, const uint32_t *b, int n) {
    for (int i = 0; i < n; i++) {
        if (a[i] != b[i]) {
            return 0;
        }
    }
    return 1;
}

/*
 * Issue a command and wait for it to complete.
 *
 * Completion is detected via STATUS.VALID: Adams Bridge parks the sequencer at
 * the op's end state (e.g. MLDSA_KG_E / SIGN_E / VERIFY_E) with VALID set;
 * STATUS.READY only re-asserts after a zeroize/reset. VALID is sticky until
 * zeroize, so this is correct only for the first op after reset/zeroize.
 */
static inline int abr_run_command(const char *what, uint32_t cmd) {
    if (abr_wait_ready() != 0) {
        printf("  [%s] timeout waiting for READY\n", what);
        return -1;
    }
    WRITE_REG(ABR_MLDSA_CTRL, cmd);
    if (poll_reg_timeout(ABR_MLDSA_STATUS, ABR_ST_VALID, ABR_ST_VALID, ABR_POLL_TIMEOUT) != 0) {
        printf("  [%s] timeout waiting for VALID\n", what);
        return -1;
    }
    uint32_t st = READ_REG(ABR_MLDSA_STATUS);
    if (st & ABR_ST_ERROR) {
        printf("  [%s] STATUS.ERROR set (status=0x%08x)\n", what, st);
        return -1;
    }
    return 0;
}

/*
 * Zeroize: clears secret state and returns the sequencer to RESET so the next
 * command can decode and STATUS.VALID is cleared. The engine is parked off
 * RESET (READY=0) when this is called, so waiting for READY=1 detects the
 * zeroize completing.
 */
static inline int abr_zeroize(void) {
    WRITE_REG(ABR_MLDSA_CTRL, ABR_CTRL_ZEROIZE);
    if (abr_wait_ready() != 0) {
        printf("  [zeroize] timeout waiting for READY\n");
        return -1;
    }
    return 0;
}

#endif /* SEP_ABR_MLDSA_H */
