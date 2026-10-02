/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    // An unlocked cold reset is writable
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR, 0x1);

    // Lock the cold reset of a second subsystem
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR, 0x2);

    // The locked cold reset must ignore the write
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR, 0x3);

    uint32_t cold_reset_read = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR);

    if (cold_reset_read != 0x1) {
        test_fail(hartid);
    }

    // The lock is set-only, so writing zero must not clear it
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR, 0x0);

    uint32_t cold_reset_lock = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR);

    if (cold_reset_lock != 0x2) {
        test_fail(hartid);
    }

    test_pass(hartid);
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
    } else {
        return other_main(hartid);
    }
}
