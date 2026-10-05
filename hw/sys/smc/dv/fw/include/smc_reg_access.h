/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_REG_ACCESS_H
#define SMC_REG_ACCESS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "smc.h"

/* Generic MMIO register accessors over the native PeakRDL SMC_TOP_* map. */

static inline void write_reg(uint64_t addr, uint32_t value) {
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)addr;
    *p_addr = value;
}

static inline uint32_t read_reg(uint64_t addr) {
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline uint64_t read_reg_64(uint64_t addr) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline void write64_reg(uint64_t addr, uint64_t value) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
    *p_addr = value;
}

static inline uint64_t read64_reg(uint64_t addr) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline void write16_reg(uint64_t addr, uint16_t value) {
    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)addr;
    *p_addr = value;
}

static inline uint16_t read16_reg(uint64_t addr) {
    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)addr;
    return *p_addr;
}

#endif /* SMC_REG_ACCESS_H */
