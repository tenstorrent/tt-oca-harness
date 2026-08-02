/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Adams Bridge ML-DSA-87 KM-driven seed sideload test.
 *
 * Verifies the end-to-end Key-Manager -> KV-shim -> Adams Bridge seed path:
 *
 *   KM CMD_KEY_LOAD + CMD_KEY_TRANSFER(dest=abr_mldsa_seed)
 *      -> KM ROM writes dual XOR shares into abr_wrapper_key_reg.MLDSA_SEED
 *      -> sep_abr_kv_shim reconstructs the seed and serves it on kv_read[0]
 *      -> abr_ctrl's kv_read_client copies it into MLDSA_SEED (KV RD ctrl)
 *      -> KEYGEN
 *
 * The KM-sourced public key is compared against a golden public key produced by
 * a direct software-seed KEYGEN using the SAME seed. abr_ctrl writes the
 * KV-sourced seed in reverse dword order relative to a direct SW write
 * (abr_ctrl.sv: kv_mldsa_seed_write_offset == SEED_NUM_DWORDS-1-dword), so a
 * dword-PALINDROMIC seed (seed[i] == seed[7-i]) is used to make the PK equality
 * check robust to that reversal (and to any KM-side ordering).
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "abr_mldsa.h"
#include "km_mailbox.h"

/*
 * Dword-palindromic seed: seed[i] == seed[7-i]. Invariant under the KV-client
 * dword reversal so PK(direct) and PK(KM sideload) can be compared directly.
 */
static const uint32_t k_seed_pal[MLDSA_SEED_WORDS] = {
    0x0badc0deu, 0x13572468u, 0xa5a5a5a5u, 0xfeedfaceu,
    0xfeedfaceu, 0xa5a5a5a5u, 0x13572468u, 0x0badc0deu
};

static uint32_t g_pk_direct[MLDSA_PK_WORDS];
static uint32_t g_pk_km[MLDSA_PK_WORDS];

/* Phase 1: golden PK from a direct software-seed KEYGEN. */
static int keygen_direct(uint32_t *pk_out)
{
    abr_write_array(ABR_MLDSA_SEED, k_seed_pal, MLDSA_SEED_WORDS);
    abr_write_array(ABR_MLDSA_ENTROPY, k_entropy, MLDSA_ENTROPY_WORDS);

    if (abr_run_command("keygen-direct", ABR_CMD_KEYGEN) != 0) {
        return -1;
    }
    abr_read_array(ABR_MLDSA_PUBKEY, pk_out, MLDSA_PK_WORDS);
    if (!abr_words_any_nonzero(pk_out, MLDSA_PK_WORDS)) {
        printf("  direct PK is all zero (keygen produced no output)\n");
        return -1;
    }
    return 0;
}

/*
 * Phase 2: KM pushes the same seed as dual shares, the shim serves it on
 * kv_read[0], and abr_ctrl copies it into MLDSA_SEED when READ_EN is set.
 */
static int keygen_km_sideload(uint32_t *pk_out)
{
    if (km_release_reset() != 0) {
        printf("  KM reset release failed\n");
        return -1;
    }
    if (km_wait_ready() != 0) {
        printf("  KM boot-ready banner not received\n");
        return -1;
    }
    if (km_load_and_transfer_key(k_seed_pal, MLDSA_SEED_WORDS,
                                 KM_DEST_ABR_MLDSA_SEED, 0) != 0) {
        printf("  KM load/transfer of ABR seed failed\n");
        return -1;
    }

    /* Entropy still comes from software; only the seed is sideloaded. */
    abr_write_array(ABR_MLDSA_ENTROPY, k_entropy, MLDSA_ENTROPY_WORDS);

    /*
     * Tell abr_ctrl to pull the seed from the KV lane (shim) instead of the
     * SW-written MLDSA_SEED register. The launched KEYGEN is masked until the
     * KV read completes; STATUS.READY (which abr_run_command waits on) folds in
     * kv_mldsa_seed_ready, so the command is not lost.
     */
    WRITE_REG(ABR_MLDSA_KV_RD_SEED_CTRL, ABR_KV_RD_SEED_READ_EN);

    if (abr_run_command("keygen-km", ABR_CMD_KEYGEN) != 0) {
        return -1;
    }
    abr_read_array(ABR_MLDSA_PUBKEY, pk_out, MLDSA_PK_WORDS);
    if (!abr_words_any_nonzero(pk_out, MLDSA_PK_WORDS)) {
        printf("  KM PK is all zero (keygen produced no output)\n");
        return -1;
    }
    return 0;
}

int main(void)
{
    int pass = 1;

    sep_outbound_filter_init();

    printf("\n=== Adams Bridge ML-DSA-87 KM-driven Seed Sideload Test ===\n");

    /* Phase 1: golden direct-seed keygen. */
    if (keygen_direct(g_pk_direct) != 0) {
        pass = 0;
        goto done;
    }
    printf("  direct PK[0..3]=0x%08x 0x%08x 0x%08x 0x%08x\n",
           g_pk_direct[0], g_pk_direct[1], g_pk_direct[2], g_pk_direct[3]);

    /* Return the sequencer to RESET / clear VALID before the second op. */
    if (abr_zeroize() != 0) {
        pass = 0;
        goto done;
    }

    /* Phase 2: KM-sideloaded seed keygen. */
    if (keygen_km_sideload(g_pk_km) != 0) {
        pass = 0;
        goto done;
    }
    printf("  KM     PK[0..3]=0x%08x 0x%08x 0x%08x 0x%08x\n",
           g_pk_km[0], g_pk_km[1], g_pk_km[2], g_pk_km[3]);

    if (!abr_words_equal(g_pk_direct, g_pk_km, MLDSA_PK_WORDS)) {
        printf("  MISMATCH: KM-sideloaded PK != direct-seed PK\n");
        pass = 0;
    }

    /* Best-effort cleanup: shred the sideloaded seed. */
    (void)km_shred_engine(KM_DEST_ABR_MLDSA_SEED);

done:
    if (pass) {
        printf("\n=== ABR KM SEED SIDELOAD TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== ABR KM SEED SIDELOAD TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
