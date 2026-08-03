/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Adams Bridge ML-DSA-87 KeyGen+Sign test (software seed).
 *
 * Single KEYGEN_SIGN operation: keygen then sign on-the-fly (the SK is never
 * stored), ending with VALID set. Loads a fixed seed/entropy/msg/sign_rnd, runs
 * the op, and checks the signature commitment c~ and the public key are
 * non-zero. Exercises the full keygen + sign datapath in one op.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "abr_mldsa.h"

static uint32_t g_pk[MLDSA_PK_WORDS];

int main(void) {
    int pass = 1;

    sep_outbound_filter_init();

    printf("\n=== Adams Bridge ML-DSA-87 KeyGen+Sign Test (software seed) ===\n");

    abr_write_array(ABR_MLDSA_SEED, k_seed, MLDSA_SEED_WORDS);
    abr_write_array(ABR_MLDSA_ENTROPY, k_entropy, MLDSA_ENTROPY_WORDS);
    abr_write_array(ABR_MLDSA_MSG, k_msg, MLDSA_MSG_WORDS);
    abr_write_array(ABR_MLDSA_SIGN_RND, k_sign_rnd, MLDSA_SIGN_RND_WORDS);

    if (abr_run_command("keygen+sign", ABR_CMD_KEYGEN_SIGN) != 0) {
        pass = 0;
    } else {
        uint32_t c_sig[MLDSA_CHASH_WORDS];
        abr_read_array(ABR_MLDSA_SIGNATURE, c_sig, MLDSA_CHASH_WORDS);
        if (!abr_words_any_nonzero(c_sig, MLDSA_CHASH_WORDS)) {
            printf("  signature is all zero (keygen+sign produced no output)\n");
            pass = 0;
        } else {
            printf("  c~[0..3]=0x%08x 0x%08x 0x%08x 0x%08x\n", c_sig[0], c_sig[1], c_sig[2],
                   c_sig[3]);
        }
        abr_read_array(ABR_MLDSA_PUBKEY, g_pk, MLDSA_PK_WORDS);
        if (!abr_words_any_nonzero(g_pk, MLDSA_PK_WORDS)) {
            printf("  PK is all zero\n");
            pass = 0;
        } else {
            printf("  PK[0..1]=0x%08x 0x%08x\n", g_pk[0], g_pk[1]);
        }
    }

    if (pass) {
        printf("\n=== ABR KEYGEN+SIGN TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== ABR KEYGEN+SIGN TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
