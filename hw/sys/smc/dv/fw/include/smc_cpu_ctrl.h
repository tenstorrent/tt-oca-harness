/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_CPU_CTRL_H
#define SMC_CPU_CTRL_H

#include "smc_reg_access.h"

/* SMC_CPU_CTRL register-block helpers: periph window, scratch, postcode. */

/* The OCCP master-BFM tests address the scratch window through per-register
 * symbols; the generated headers expose it as an indexed base macro, so these
 * aliases map one onto the other.
 * Scratch registers are 64-bit strided, matching write_scratch/read_scratch. */
#define SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(n) \
    (SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0) + ((n) * sizeof(uint64_t)))

#define SMC_CPU_CTRL_SCRATCH_0__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(0)
#define SMC_CPU_CTRL_SCRATCH_1__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(1)
#define SMC_CPU_CTRL_SCRATCH_2__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(2)
#define SMC_CPU_CTRL_SCRATCH_3__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(3)
#define SMC_CPU_CTRL_SCRATCH_4__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(4)
#define SMC_CPU_CTRL_SCRATCH_5__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(5)
#define SMC_CPU_CTRL_SCRATCH_6__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(6)
#define SMC_CPU_CTRL_SCRATCH_7__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(7)
#define SMC_CPU_CTRL_SCRATCH_8__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(8)
#define SMC_CPU_CTRL_SCRATCH_9__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(9)
#define SMC_CPU_CTRL_SCRATCH_10__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(10)
#define SMC_CPU_CTRL_SCRATCH_11__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(11)
#define SMC_CPU_CTRL_SCRATCH_12__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(12)
#define SMC_CPU_CTRL_SCRATCH_13__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(13)
#define SMC_CPU_CTRL_SCRATCH_14__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(14)
#define SMC_CPU_CTRL_SCRATCH_15__REG_ADDR SMC_CPU_CTRL_SCRATCH_N__REG_ADDR(15)

/* Aliases for the registers occp_register_access_test walks. GLOBAL_BASE lives
 * in the BASE_CONFIG block, not CPU_CTRL, so its alias points outside the
 * CPU_CTRL map. */
#define SMC_CPU_CTRL_DUMMY_ROM_0_REG_ADDR SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_0_BASE_ADDR
#define SMC_CPU_CTRL_GLOBAL_BASE_REG_ADDR SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR
#define SMC_MISC_WRAP_SCRATCH_COLD_REG_MAP_BASE_ADDR \
    SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)
#define SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_REG_ADDR \
    SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR

static inline void write_periph_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_periph_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_smc_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *addr_ptr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    *addr_ptr = value;
}

static inline uint64_t read_smc_reg(uint64_t offset) {
    volatile uint64_t *addr_ptr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    return *addr_ptr;
}

static inline void write_scratch(uint8_t scratch_num, uint32_t value) {
    volatile uint32_t *addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0) +
                                         (scratch_num * sizeof(uint64_t)));
    *addr = value;
}

static inline uint32_t read_scratch(uint8_t scratch_num) {
    volatile uint32_t *addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0) +
                                         (scratch_num * sizeof(uint64_t)));
    return *addr;
}

static inline void write_postcode(uint32_t value) {
    write_scratch(0, value);
}

#endif /* SMC_CPU_CTRL_H */
