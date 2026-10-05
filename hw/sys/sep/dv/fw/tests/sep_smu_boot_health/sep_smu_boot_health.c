/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_boot_health - minimal SEP boot-health firmware.
 *
 * Proves the SEP runs by default after reset and retires this image with no
 * SMC, mailbox or outbound filter setup. It writes a liveness marker and then
 * a pass marker to SEP-local cold scratch, reading each back, and parks in the
 * pass loop. A read-back mismatch writes a fail marker and parks in the fail
 * loop. The testbench classifies the run by which loop the SEP parks in.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"

#define BH_COLD_SCRATCH7 SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)
#define BH_ALIVE 0x001A11E0u /* first liveness marker */
#define BH_PASS 0x001600D1u  /* boot-health PASS marker */
#define BH_FAIL 0x001FA11Eu  /* read-back mismatch marker */

/* Named terminal loops: the testbench classifies the run by which one the SEP parks in. */
__attribute__((noinline, used)) void sep_smu_boot_health_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((noinline, used)) void sep_smu_boot_health_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    WRITE_REG(BH_COLD_SCRATCH7, BH_ALIVE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(BH_COLD_SCRATCH7) != BH_ALIVE) {
        WRITE_REG(BH_COLD_SCRATCH7, BH_FAIL);
        sep_smu_boot_health_fail_loop();
    }

    WRITE_REG(BH_COLD_SCRATCH7, BH_PASS);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(BH_COLD_SCRATCH7) != BH_PASS) {
        WRITE_REG(BH_COLD_SCRATCH7, BH_FAIL);
        sep_smu_boot_health_fail_loop();
    }

    sep_smu_boot_health_pass_loop();
}
