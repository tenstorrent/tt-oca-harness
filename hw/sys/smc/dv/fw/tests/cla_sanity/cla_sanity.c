/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC_CLA_001 — SPEC-blocked placeholder (SF-001/SF-002 waived).
 * Record the SF ledger only; do not emit feature CHK-* lines or a
 * cannot-fail "nonvacuous" checker while SF-001 remains waived.
 */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/cpu.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    simputs("  SF_RECORDED: SF-001 waived SPEC_REVIEW ledger\n");
    simputs("  SF_RECORDED: SF-002 waived SPEC_REVIEW ledger\n");
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
