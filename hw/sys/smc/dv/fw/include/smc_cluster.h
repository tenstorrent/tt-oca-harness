/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_CLUSTER_H
#define SMC_CLUSTER_H

#include "smc_reg_access.h"

/* Per-hart cluster-core register blocks: Bus Error Unit (BEU) and watchdog (WDT). */

static inline void write_beu_reg(int hartid, uint64_t offset, uint64_t value) {
    uint64_t BASE_ADDRESS_BEU;
    if (hartid == 0) {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR;
    } else {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_BEU + offset);
    *p_addr = value;
}

static inline uint64_t read_beu_reg(int hartid, uint64_t offset) {
    uint64_t BASE_ADDRESS_BEU;
    if (hartid == 0) {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR;
    } else {
        BASE_ADDRESS_BEU = SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_BEU + offset);
    return *p_addr;
}

static inline void write_wdt_reg(int hartid, uint64_t offset, uint64_t value) {
    uint64_t BASE_ADDRESS_WDT;
    if (hartid == 0) {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR;
    } else {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_WDT + offset);
    *p_addr = value;
}

static inline uint64_t read_wdt_reg(int hartid, uint64_t offset) {
    uint64_t BASE_ADDRESS_WDT;
    if (hartid == 0) {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR;
    } else {
        BASE_ADDRESS_WDT = SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_WDT + offset);
    return *p_addr;
}

#endif /* SMC_CLUSTER_H */
