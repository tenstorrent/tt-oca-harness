/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

/*
 * SMU-SEP boot shim.
 *
 * Arms the CLA boot path for the SEP from a dedicated reset entry, so the
 * SMU-SEP boot does not depend on the generic multihart C runtime reaching
 * main first.
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
}
