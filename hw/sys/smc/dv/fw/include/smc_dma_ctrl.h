/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_DMA_CTRL_H
#define SMC_DMA_CTRL_H

#include "smc_reg_access.h"

/* Raw DMA_CTRL register-block accessors. */

static inline void write_dma_ctrl_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_DMA_CTRL_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_dma_ctrl_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_DMA_CTRL_BASE_ADDR + offset);
    return *p_addr;
}

#endif /* SMC_DMA_CTRL_H */
