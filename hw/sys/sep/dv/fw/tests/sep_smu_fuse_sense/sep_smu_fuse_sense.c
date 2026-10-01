/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_fuse_sense - firmware consumer of two fuse-sense CSRs.
 *
 * First instruction stream after boot reads 0x10A30140 / 0x10930400 /
 * 0x10A30150 (capture the pre-completion window if the CPU is already live),
 * then polls until bit0=1 on all three, then publishes the first samples.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_efuse.h"
#include "sep_smu_fuse_sense_protocol.h"

#define FUSE_SENSE_SCRATCH4 SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4)
#define FUSE_SENSE_SCRATCH5 SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5)
#define FUSE_SENSE_SCRATCH6 SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6)
#define FUSE_SENSE_SCRATCH7 SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)
#define FUSE_SENSE_POLL_LIMIT 1000000u

#define FUSE_SENSE_SMC_STATUS SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR
#define FUSE_SENSE_SEP_STATUS SEP_TOP_SEP_CPU_CTRL_SEP_FUSE_SENSE_STATUS_BASE_ADDR

__attribute__((used, noinline, noreturn)) void sep_smu_fuse_sense_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_fuse_sense_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

static void fail(void) {
    WRITE_REG(FUSE_SENSE_SCRATCH6, FUSE_SENSE_FAIL);
    sep_smu_fuse_sense_fail_loop();
}

int main(void) {
    uint32_t first_smc;
    uint32_t first_ifc;
    uint32_t first_sep;
    uint32_t smc;
    uint32_t ifc;
    uint32_t sep_st;
    uint32_t i;

    first_smc = READ_REG(FUSE_SENSE_SMC_STATUS);
    first_ifc = READ_REG(SEP_EFUSE_IFC_STATUS);
    first_sep = READ_REG(FUSE_SENSE_SEP_STATUS);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    smc = first_smc;
    ifc = first_ifc;
    sep_st = first_sep;
    for (i = 0; i < FUSE_SENSE_POLL_LIMIT; i++) {
        if (((smc & 1u) != 0u) && ((ifc & 1u) != 0u) && ((sep_st & 1u) != 0u)) {
            break;
        }
        smc = READ_REG(FUSE_SENSE_SMC_STATUS);
        ifc = READ_REG(SEP_EFUSE_IFC_STATUS);
        sep_st = READ_REG(FUSE_SENSE_SEP_STATUS);
    }
    if (((smc & 1u) == 0u) || ((ifc & 1u) == 0u) || ((sep_st & 1u) == 0u)) {
        fail();
    }

    WRITE_REG(FUSE_SENSE_SCRATCH4, first_smc);
    WRITE_REG(FUSE_SENSE_SCRATCH5, first_ifc);
    WRITE_REG(FUSE_SENSE_SCRATCH7, first_sep);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(FUSE_SENSE_SCRATCH4) != first_smc) {
        fail();
    }
    if (READ_REG(FUSE_SENSE_SCRATCH5) != first_ifc) {
        fail();
    }
    if (READ_REG(FUSE_SENSE_SCRATCH7) != first_sep) {
        fail();
    }

    WRITE_REG(FUSE_SENSE_SCRATCH6, FUSE_SENSE_PUBLISH);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    sep_smu_fuse_sense_pass_loop();
    return 0;
}
