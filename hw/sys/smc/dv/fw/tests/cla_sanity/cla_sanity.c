/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief CLA Sanity Test - boot check
 *
 * Passes once the SMC CPU runs this SRAM image. The test accesses no CLA
 * register, emits no CHK-* line and claims no feature coverage.
 */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    simputs("  PLACEHOLDER: no CLA register is accessed by this test.\n");
    simputs("  PLACEHOLDER: a pass here means the CPU booted, nothing more.\n");
    test_pass(0);
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
