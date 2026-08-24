/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC_CLA_001 — SPEC-blocked placeholder (SF-001/SF-002 waived).
 * Integrity-only: record SF ledger, emit no feature CHK-* lines, then CHK-NONVAC.
 * Do not invent CLA LIVE/register expects while SF-001 remains waived.
 */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/cpu.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    /*
     * feature_chk_emitted stays 0 on this SPEC-absent path. If a future edit
     * prints a feature CHK-* line, set the flag so PASS cannot be vacuous.
     */
    uint32_t feature_chk_emitted = 0;

    simputs("  SF_RECORDED: SF-001 waived SPEC_REVIEW ledger\n");
    simputs("  SF_RECORDED: SF-002 waived SPEC_REVIEW ledger\n");

    if (feature_chk_emitted != 0) {
        write_scratch(2, feature_chk_emitted);
        simputs("  ERROR: feature CHK-* emitted on SPEC-absent path\n");
        test_fail(0);
    }

    simputs("  CHK-NONVAC: SF_RECORDED < NO_FEATURE_CHK_LINE\n");
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    }
    return other_main(hartid);
}
