/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    uint64_t mutex_0;

    do {
        mutex_0 = read_periph_reg(
            (SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR(0) - SMC_TOP_SMC_CPU_CTRL_BASE_ADDR));
    } while (mutex_0 == 0);

    if (mutex_0 == 1) {
        write_scratch(hartid, 0xbeefbeef);
    }

    write_periph_reg((SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR(0) - SMC_TOP_SMC_CPU_CTRL_BASE_ADDR),
                     0x1);

    uint32_t scratch_reg_0_data, scratch_reg_1_data, scratch_reg_2_data, scratch_reg_3_data;

    // Core 0 waits for the secondary cores, which mark before they increment.
    uint64_t semaphore;
    if (hartid == 0) {
        do {
            semaphore = read_periph_reg(
                (SMC_TOP_SMC_CPU_CTRL_SEMA_BASE_ADDR(0) - SMC_TOP_SMC_CPU_CTRL_BASE_ADDR));
        } while (semaphore < 3);

        scratch_reg_0_data = read_scratch(0);
        scratch_reg_1_data = read_scratch(1);
        scratch_reg_2_data = read_scratch(2);
        scratch_reg_3_data = read_scratch(3);

        if ((scratch_reg_0_data != 0xbeefbeef) || (scratch_reg_1_data != 0xbeefbeef) ||
            (scratch_reg_2_data != 0xbeefbeef) || (scratch_reg_3_data != 0xbeefbeef)) {
            test_fail(hartid);
        }

        test_pass(hartid);
    } else {
        write_periph_reg((SMC_TOP_SMC_CPU_CTRL_SEMA_BASE_ADDR(0) - SMC_TOP_SMC_CPU_CTRL_BASE_ADDR),
                         0x1);
    }

    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    return main();
}
