/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_MEM_H
#define SMC_MEM_H

#include "smc_reg_access.h"

/* Scratchpad memory (SPM) and the zeroer engine. */

static inline void write_spm(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    *p_addr = value;
}

static inline void write_spm64(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_spm(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    return *p_addr;
}

static inline uint64_t read_spm64(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_zeroer_ctrl_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_ZEROER_CTRL_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_zeroer_ctrl_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_ZEROER_CTRL_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_zeros(const uint32_t addr, const uint32_t size, const bool int_en) {
    write_zeroer_ctrl_reg((SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR - SMC_TOP_ZEROER_CTRL_BASE_ADDR),
                          addr);
    write_zeroer_ctrl_reg((SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR - SMC_TOP_ZEROER_CTRL_BASE_ADDR),
                          size);
    write_zeroer_ctrl_reg(
        (SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR - SMC_TOP_ZEROER_CTRL_BASE_ADDR), int_en);

    while (read_zeroer_ctrl_reg(
        (SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR - SMC_TOP_ZEROER_CTRL_BASE_ADDR)))
        ;
}

#endif /* SMC_MEM_H */
