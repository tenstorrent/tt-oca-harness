/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMU-SEP CLA boot programming.
 *
 * The CLA node0 EAP custom actions drive SEP CPU control (see
 * hw/sys/smu/rtl/smu.sv):
 *   [1] mpc_debug_run_req, [2] mpc_reset_run_req, [4] i_cpu_run_req.
 *
 * Register addresses and field layout come from the generated map (smc_addr.h
 * and the generated smc_cla.h, both reached through smc_reg_access.h).
 *
 * dfd_top_cla_dst_apb has no CDFDCSR arm MMR, and smc_dfd_wrap ties
 * i_cla_fuse_dis/i_cla_clk_dis/i_cla_clk_dis_ctrl low, so the block powers up
 * enabled and CDBGCLACTRLSTATUS is the only gate.
 */

#ifndef SMC_CLA_BOOT_H
#define SMC_CLA_BOOT_H

#include <stdbool.h>
#include <stdint.h>

#include "smc_reg_access.h"

/* The CLA block is an array in smc.rdl (NUM_CLA_INST), so the generated bases
 * take an instance index. smc_dfd_wrap builds one, hence 0. */
#define SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR SMC_TOP_SMC_CLA_CLA_CDBGCLACTRLSTATUS_BASE_ADDR(0)
#define SMC_CLA_CDBGNODE0EAP0_REG_ADDR SMC_TOP_SMC_CLA_CLA_CDBGNODE0EAP0_BASE_ADDR(0)
#define SMC_CLA_CDBGNODE0EAP1_REG_ADDR SMC_TOP_SMC_CLA_CLA_CDBGNODE0EAP1_BASE_ADDR(0)

static inline uint64_t smu_sep_cla_field(uint64_t value, uint64_t mask, uint32_t shift) {
    return (value << shift) & mask;
}

static inline uint64_t smu_sep_cla_node0_eap_value(uint32_t action0, uint32_t action1,
                                                   bool action1_enable) {
    const uint64_t logical_op_nor = 3ULL;
    const uint64_t event_none0 = 63ULL;
    const uint64_t event_none1 = 62ULL;

    return smu_sep_cla_field(logical_op_nor, DFD_CLA__CDBGNODE0EAP0__LOGICALOP_bm,
                             DFD_CLA__CDBGNODE0EAP0__LOGICALOP_bp) |
           smu_sep_cla_field(event_none0, DFD_CLA__CDBGNODE0EAP0__EVENTTYPE0_bm,
                             DFD_CLA__CDBGNODE0EAP0__EVENTTYPE0_bp) |
           smu_sep_cla_field(event_none1, DFD_CLA__CDBGNODE0EAP0__EVENTTYPE1_bm,
                             DFD_CLA__CDBGNODE0EAP0__EVENTTYPE1_bp) |
           smu_sep_cla_field(action0, DFD_CLA__CDBGNODE0EAP0__CUSTOMACTION0_bm,
                             DFD_CLA__CDBGNODE0EAP0__CUSTOMACTION0_bp) |
           smu_sep_cla_field(action1, DFD_CLA__CDBGNODE0EAP0__CUSTOMACTION1_bm,
                             DFD_CLA__CDBGNODE0EAP0__CUSTOMACTION1_bp) |
           (uint64_t)DFD_CLA__CDBGNODE0EAP0__CUSTOMACTION0ENABLE_bm |
           (action1_enable ? (uint64_t)DFD_CLA__CDBGNODE0EAP0__CUSTOMACTION1ENABLE_bm : 0ULL);
}

static inline void smu_sep_program_real_cla_boot(void) {
    /*
     * mpc_reset_run_req = ~cla[2], so action[2]=1 selects Debug Mode (halt) and
     * parks the SEP core. A normal boot fires only the run requests {1,4};
     * leaving [2] deasserted keeps mpc_reset_run_req = 1 (Normal/run).
     */
    write64_reg(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR,
                (uint64_t)DFD_CLA__CDBGCLACTRLSTATUS__ENABLECLA_bm |
                    (uint64_t)DFD_CLA__CDBGCLACTRLSTATUS__ENABLEEAP_bm);
    write64_reg(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, smu_sep_cla_node0_eap_value(1u, 4u, true));
    write64_reg(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, smu_sep_cla_node0_eap_value(4u, 4u, false));
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

#endif /* SMC_CLA_BOOT_H */
