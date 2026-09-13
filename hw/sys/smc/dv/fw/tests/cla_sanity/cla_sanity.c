/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC_CLA_001 -- SPEC-blocked placeholder. PROVES NOTHING ABOUT CLA.
 *
 * This test touches no CLA register: it boots, prints, and passes. It is
 * enrolled and green, so a reader of the regression sees a CLA row that
 * attests only to "the SMC CPU boots and runs an SRAM image" -- something
 * every other firmware test already establishes. It emits no CHK-* line, so
 * it claims no feature coverage, but the green row still reads as CLA
 * coverage. Giving it real CLA checks (CLA_CTRL_CG_ENABLE against its declared
 * default, with a failure leg) or de-enrolling the row is the owner's call.
 *
 * It prints no waiver or ledger attestation: nothing in the tree records one,
 * and a kept log must not carry a waiver no human signed.
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
