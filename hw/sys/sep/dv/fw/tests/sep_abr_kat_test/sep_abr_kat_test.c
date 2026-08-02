/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Adams Bridge ML-DSA-87 self-consistency KAT (software seed).
 *
 * A golden-free known-answer test: sign a message, then verify that signature,
 * and confirm the verifier's recomputed challenge equals the signature's
 * commitment c~. Because Adams Bridge parks at the op end state after a command
 * (no auto-return to RESET), a zeroize is issued between the sign and verify so
 * the verify command can decode.
 *
 *   1. KEYGEN_SIGN  : seed,msg -> SIGNATURE (+ PK). Save PK and the full SIG.
 *   2. ZEROIZE      : return the engine to RESET.
 *   3. VERIFY       : re-supply PK + SIGNATURE + MSG -> VERIFY_RES.
 *   PASS iff VERIFY_RES == SIGNATURE[0..15] (c~).
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "abr_mldsa.h"

static uint32_t g_pk[MLDSA_PK_WORDS];
static uint32_t g_sig[MLDSA_SIG_WORDS];
static uint32_t g_ver[MLDSA_CHASH_WORDS];

static int run_kat(void) {
    /* 1. KeyGen + Sign (on-the-fly SK). */
    abr_write_array(ABR_MLDSA_SEED, k_seed, MLDSA_SEED_WORDS);
    abr_write_array(ABR_MLDSA_ENTROPY, k_entropy, MLDSA_ENTROPY_WORDS);
    abr_write_array(ABR_MLDSA_MSG, k_msg, MLDSA_MSG_WORDS);
    abr_write_array(ABR_MLDSA_SIGN_RND, k_sign_rnd, MLDSA_SIGN_RND_WORDS);
    if (abr_run_command("keygen+sign", ABR_CMD_KEYGEN_SIGN) != 0) {
        return -1;
    }
    abr_read_array(ABR_MLDSA_PUBKEY, g_pk, MLDSA_PK_WORDS);
    abr_read_array(ABR_MLDSA_SIGNATURE, g_sig, MLDSA_SIG_WORDS);
    printf("  signed: c~[0..1]=0x%08x 0x%08x  PK[0..1]=0x%08x 0x%08x\n", g_sig[0], g_sig[1],
           g_pk[0], g_pk[1]);
    if (!abr_words_any_nonzero(g_sig, MLDSA_CHASH_WORDS)) {
        printf("  signature commitment is all zero\n");
        return -1;
    }

    /* 2. Zeroize -> engine back to RESET (clears VALID so VERIFY can decode). */
    if (abr_zeroize() != 0) {
        return -1;
    }

    /* 3. Verify: re-supply public key, signature and message. */
    abr_write_array(ABR_MLDSA_PUBKEY, g_pk, MLDSA_PK_WORDS);
    abr_write_array(ABR_MLDSA_SIGNATURE, g_sig, MLDSA_SIG_WORDS);
    abr_write_array(ABR_MLDSA_MSG, k_msg, MLDSA_MSG_WORDS);
    if (abr_run_command("verify", ABR_CMD_VERIFY) != 0) {
        return -1;
    }
    abr_read_array(ABR_MLDSA_VERIFY_RES, g_ver, MLDSA_CHASH_WORDS);
    if (!abr_words_equal(g_ver, g_sig, MLDSA_CHASH_WORDS)) {
        printf("  VERIFY_RES mismatch: c_ver[0]=0x%08x c_sig[0]=0x%08x\n", g_ver[0], g_sig[0]);
        return -1;
    }
    printf("  VERIFY_RES matches c~ -> signature VALID\n");
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n=== Adams Bridge ML-DSA-87 Self-Consistency KAT (software seed) ===\n");

    int pass = (run_kat() == 0);

    if (pass) {
        printf("\n=== ABR ML-DSA-87 SELF-CONSISTENCY KAT PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== ABR ML-DSA-87 SELF-CONSISTENCY KAT FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
