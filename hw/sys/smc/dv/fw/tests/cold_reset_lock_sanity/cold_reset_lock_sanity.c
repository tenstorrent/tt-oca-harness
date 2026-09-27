/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

METAL_LOCK_DECLARE(mmio_lock);
METAL_ATOMIC_DECLARE(shared_counter);

volatile bool _start_other = 0;
static uint32_t checkin_count = 0;

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    // write to cold reset to ensure it is writable
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR, 0x1);

    // write cold reset lock, lock second cold reset
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR, 0x2);

    // write to cold reset to index 1
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR, 0x3);

    uint32_t cold_reset_read = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR);

    if (cold_reset_read != 0x1) {
        test_fail(hartid);
    }

    // write cold reset lock, try to unlock
    write_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR, 0x0);

    uint32_t cold_reset_lock = read_reg(SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR);

    if (cold_reset_lock != 0x2) {
        test_fail(hartid);
    }

    test_pass(hartid);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
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
