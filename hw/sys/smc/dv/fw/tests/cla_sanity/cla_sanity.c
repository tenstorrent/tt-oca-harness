/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC_CLA_001 — SF-001/SF-002 spec-finding ledger entries only: this image
 * drives no CLA register and emits no feature CHK-* token.
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
