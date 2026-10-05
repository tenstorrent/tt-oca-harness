/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

int main(void) {

    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        uint32_t version_low, version_low_expected;
        uint32_t version_high, version_high_expected;
        uint32_t chip_id;
        uint32_t lc_state;

        // Both version words must read their reset values
        version_low_expected = 0x000100A0;
        version_high_expected = 0x0;

        version_low = read_reg(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR);
        write_scratch(1, version_low);

        version_high = read_reg(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR);
        write_scratch(1, version_high);

        chip_id = read_reg(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR);
        write_scratch(1, chip_id);

        lc_state = read_reg(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR);
        write_scratch(1, lc_state);

        if ((version_low == version_low_expected) && (version_high == version_high_expected)) {
            test_pass(0);
        } else {
            test_fail(0);
        }
    }

    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {

    return main();
}
