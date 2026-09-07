/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC_CLA_001 -- SPEC-blocked placeholder. PROVES NOTHING ABOUT CLA.
 *
 * This test touches no CLA register: it boots, prints, and passes. It is
 * enrolled and green, so a reader of the regression sees a CLA row that
 * attests only to "the SMC CPU boots and runs an SRAM image" -- something
 * every other firmware test already establishes. Not emitting CHK-* lines
 * (the note that used to be here) keeps it from claiming feature coverage,
 * but does not stop the green row from reading as CLA coverage.
 *
 * A version with real CLA checks -- reading CLA_CTRL_CG_ENABLE against its
 * declared default with a genuine failure leg -- exists in a third checkout
 * and is commented out there. Reinstating it, or de-enrolling this row, is
 * the owner's call.
 *
 * The two SF_RECORDED lines this used to print are gone. They announced
 * "SF-001 waived SPEC_REVIEW ledger" into the kept log while no such ledger
 * exists anywhere in the tree, so the run's own artifact carried a waiver
 * attestation that no human had signed.
 */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/cpu.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    simputs("  PLACEHOLDER: no CLA register is accessed by this test.\n");
    simputs("  PLACEHOLDER: a pass here means the CPU booted, nothing more.\n");
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
