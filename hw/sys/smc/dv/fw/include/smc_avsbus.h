/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_AVSBUS_H
#define SMC_AVSBUS_H

#include "smc_reg_access.h"

static inline void write_apb2avsbus_ctrl_reg(uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint32_t read_abp2avsbus_ctrl_reg(uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR + offset);
    return *p_addr;
}

#endif /* SMC_AVSBUS_H */
