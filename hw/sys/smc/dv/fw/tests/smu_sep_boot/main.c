/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

/*
 * SMU-SEP DV boot shim.
 *
 * The reset vector points at smu_sep_boot_entry: the SMU-SEP real-CLA boot flow
 * must not depend on the generic multihart C runtime reaching main before CLA is
 * armed.
 */
void smu_sep_boot_entry(void) __attribute__((naked, section(".init"), used));
void smu_sep_boot_entry(void) {
    __asm__ volatile(".option push\n"
                     ".option norvc\n"
                     "csrr a0, mhartid\n"
                     "bnez a0, 0f\n"
                     "la gp, __global_pointer$\n"
                     "la sp, _sp\n"
                     "andi sp, sp, -16\n"
                     "call main\n"
                     "0:\n"
                     "wfi\n"
                     "j 0b\n"
                     ".option pop\n");
}

int main(void) {
    smu_sep_dv_test_bringup();
    test_pass(0);

    while (true) {
        __asm__ volatile("wfi");
    }

    return 0;
}
