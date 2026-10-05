/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

/* Span whose quarter is the per-hart destination offset; smaller than the SPM. */
#define SPM_TEST_WINDOW_SIZE 0x1000u

int main(void) {

    int hartid = metal_cpu_get_current_hartid();

    write_scratch(4 + hartid, 0x54045);
    for (int i = 0; i < 4096; i++) {
        write64_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + hartid * (SPM_TEST_WINDOW_SIZE / 4) + i * 8,
                    read64_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + i * 8));
    }
    write_scratch(4 + hartid, 0xF18A1);

    if (hartid == 0) {
        while ((read_scratch(5) != 0xF18A1) || (read_scratch(6) != 0xF18A1) ||
               (read_scratch(7) != 0xF18A1)) {
        }
        test_pass(0);
    }

    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {

    return main();
}
