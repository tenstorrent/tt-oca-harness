/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_boot_health  --  minimal SEP boot-health firmware.
 *
 * Pure SEP default-run boot gate (no SMC, no mailbox, no xbar, no filter/aperture). The SEP EL2
 * default-runs after its reset chain releases (cla_ext_action_custom[2]=0 -> mpc_reset_run_req_i=1,
 * sampled at reset), retires boot-ROM then this ITCM image, and proves it is alive by writing
 * ALIVE then PASS to the SEP-LOCAL cold scratch7 (0x10802038) with a read-back after each, then
 * parks in a named pass loop. A read-back mismatch writes FAIL and parks in the fail loop. cocotb
 * classifies the run by the terminal loop PC + the passively-observed cold-scratch7 markers -- no
 * STDOUT, no test_pass magic. Cold scratch7 is SEP-local (in the SEP alias region), so no outbound
 * filter or aperture setup is needed.
 */

#include <stdint.h>

#include "och_sep_common.h" /* WRITE_REG / READ_REG */
#include "sep.h"            /* SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7) */

#define BH_COLD_SCRATCH7 \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7) /* 0x10802038 (SEP-local) \
                                                   */
#define BH_ALIVE 0x001A11E0u                      /* first liveness marker */
#define BH_PASS 0x001600D1u                       /* boot-health PASS marker */
#define BH_FAIL 0x001FA11Eu                       /* read-back mismatch marker */

/* Named terminal loops -- a cocotb PC watch classifies the run by which one the SEP parks in. */
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
    /* ALIVE -> read-back -> PASS -> read-back, each fail-gated to the fail loop. */
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
    return 0;
}
