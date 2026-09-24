/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Adams Bridge ML-DSA-87 KeyGen test (software seed).
 *
 * Single KeyGen operation: load a fixed seed + entropy, run KEYGEN, wait for
 * VALID, and check the public key is non-zero. Exercises the keygen datapath
 * end-to-end through the SEP -> axi_lite_to_ahb -> AB path.
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

    printf("\n=== Adams Bridge ML-DSA-87 KeyGen Test (software seed) ===\n");

    abr_write_array(ABR_MLDSA_SEED, k_seed, MLDSA_SEED_WORDS);
    abr_write_array(ABR_MLDSA_ENTROPY, k_entropy, MLDSA_ENTROPY_WORDS);

    if (abr_run_command("keygen", ABR_CMD_KEYGEN) != 0) {
        pass = 0;
    } else {
        abr_read_array(ABR_MLDSA_PUBKEY, g_pk, MLDSA_PK_WORDS);
        if (!abr_words_any_nonzero(g_pk, MLDSA_PK_WORDS)) {
            printf("  PK is all zero (keygen produced no output)\n");
            pass = 0;
        } else {
            printf("  PK[0..3]=0x%08x 0x%08x 0x%08x 0x%08x\n", g_pk[0], g_pk[1], g_pk[2], g_pk[3]);
        }
    }

    if (pass) {
        printf("\n=== ABR KEYGEN TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== ABR KEYGEN TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
