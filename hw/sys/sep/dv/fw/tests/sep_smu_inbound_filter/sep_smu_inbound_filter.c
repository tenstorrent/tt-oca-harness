/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_inbound_filter - firmware-owned inbound rule0.
 *
 * After real fuse-sense, program SEP GLOBAL_BASE/REGION_SIZE and inbound
 * filter rule 0 (config 0x53113, START=END=A_ext). Filter CSRs are
 * write-only from the CPU (a read stalls); publish the programmed values
 * on cold scratch and park. Cocotb confirms the stored rule via passive
 * field_storage leaves (same policy as the OTP status reference read).
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_efuse.h"
#include "sep_smu_inbound_filter_protocol.h"

#define INB_FILTER_SCRATCH4 OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4)
#define INB_FILTER_SCRATCH5 OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5)
#define INB_FILTER_SCRATCH6 OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6)
#define INB_FILTER_SCRATCH7 OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)
#define INB_FILTER_SENSE_LIMIT 2000000u

#define SEP_GLOBAL_BASE_REG OCH_SEP_TOP_SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_BASE_ADDR
#define SEP_REGION_SIZE_REG OCH_SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR
#define SEP_INB_BASE OCH_SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0)
#define FILTER_CONFIG_OFFSET 0x0u
#define FILTER_START_OFFSET 0x8u
#define FILTER_END_OFFSET 0x10u

__attribute__((used, noinline, noreturn)) void sep_smu_inbound_filter_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_inbound_filter_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

static void fail(void) {
    WRITE_REG(INB_FILTER_SCRATCH6, INB_FILTER_FAIL);
    sep_smu_inbound_filter_fail_loop();
}

int main(void) {
    uint32_t status = 0;
    uint32_t i;
    uint64_t global_base;
    uint32_t region_size;

    for (i = 0; i < INB_FILTER_SENSE_LIMIT; i++) {
        status = READ_REG(SEP_EFUSE_IFC_STATUS);
        if ((status & SEP_EFUSE_SENSE_DONE) != 0u) {
            break;
        }
    }
    if ((status & SEP_EFUSE_SENSE_DONE) == 0u) {
        fail();
    }

    WRITE_REG64(SEP_GLOBAL_BASE_REG, (uint64_t)INB_FILTER_SEP_GLOBAL_BASE);
    WRITE_REG(SEP_REGION_SIZE_REG, INB_FILTER_SEP_REGION_SIZE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    global_base = READ_REG64(SEP_GLOBAL_BASE_REG);
    region_size = READ_REG(SEP_REGION_SIZE_REG);
    if (global_base != (uint64_t)INB_FILTER_SEP_GLOBAL_BASE) {
        fail();
    }
    if (region_size != INB_FILTER_SEP_REGION_SIZE) {
        fail();
    }
    if ((global_base + (uint64_t)INB_FILTER_LOCAL_SCRATCH) != (uint64_t)INB_FILTER_A_EXT) {
        fail();
    }

    WRITE_REG64(SEP_INB_BASE + FILTER_START_OFFSET, (uint64_t)INB_FILTER_A_EXT);
    WRITE_REG64(SEP_INB_BASE + FILTER_END_OFFSET, (uint64_t)INB_FILTER_A_EXT);
    WRITE_REG64(SEP_INB_BASE + FILTER_CONFIG_OFFSET, INB_FILTER_RULE_CONFIG);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    WRITE_REG(INB_FILTER_SCRATCH4, (uint32_t)INB_FILTER_A_EXT);
    WRITE_REG(INB_FILTER_SCRATCH5, (uint32_t)INB_FILTER_RULE_CONFIG);
    WRITE_REG(INB_FILTER_SCRATCH7, (uint32_t)global_base);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(INB_FILTER_SCRATCH4) != (uint32_t)INB_FILTER_A_EXT) {
        fail();
    }
    if (READ_REG(INB_FILTER_SCRATCH5) != (uint32_t)INB_FILTER_RULE_CONFIG) {
        fail();
    }
    if (READ_REG(INB_FILTER_SCRATCH7) != (uint32_t)global_base) {
        fail();
    }

    WRITE_REG(INB_FILTER_SCRATCH6, INB_FILTER_PUBLISH);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    sep_smu_inbound_filter_pass_loop();
    return 0;
}
