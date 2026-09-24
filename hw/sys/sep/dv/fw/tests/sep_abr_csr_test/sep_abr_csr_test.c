/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Adams Bridge CSR identity test.
 *
 * Reachability + identity smoke: reads the ML-DSA NAME/VERSION CSRs through the
 * SEP local fabric (AXI -> AXI4-Lite -> axi_lite_to_ahb -> AB AHB) at the ABR
 * aperture and checks NAME == "MLDSA-87". No crypto operation, so it is fast.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "abr_mldsa.h"

int main(void) {
    int pass = 1;

    sep_outbound_filter_init();

    printf("\n=== Adams Bridge CSR Identity Test (ABR @ 0x%08x) ===\n", ABR_BASE);

    uint32_t name0 = READ_REG(ABR_MLDSA_NAME0);
    uint32_t name1 = READ_REG(ABR_MLDSA_NAME1);
    uint32_t ver0 = READ_REG(ABR_MLDSA_VERSION0);
    uint32_t ver1 = READ_REG(ABR_MLDSA_VERSION1);

    printf("NAME=0x%08x%08x VERSION=0x%08x%08x\n", name1, name0, ver1, ver0);

    if (name0 != ABR_MLDSA_NAME0_EXP || name1 != ABR_MLDSA_NAME1_EXP) {
        printf("  NAME mismatch (expected 0x%08x%08x = \"MLDSA-87\")\n", ABR_MLDSA_NAME1_EXP,
               ABR_MLDSA_NAME0_EXP);
        pass = 0;
    } else {
        printf("  NAME = \"MLDSA-87\" OK\n");
    }
    if (ver0 == 0u && ver1 == 0u) {
        printf("  VERSION reads zero (CSR not responding?)\n");
        pass = 0;
    }

    if (pass) {
        printf("\n=== ABR CSR IDENTITY TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== ABR CSR IDENTITY TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
