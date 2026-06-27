/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#ifndef SMC_CPU_CTRL_H
#define SMC_CPU_CTRL_H

#include "smc_reg_access.h"

/* SMC_CPU_CTRL register-block helpers: periph window, scratch, postcode. */

static inline void write_periph_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
  *p_addr = value;
}

static inline uint64_t read_periph_reg(uint64_t offset)
{
  volatile uint64_t *p_addr =
      (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
  return *p_addr;
}

static inline void write_smc_reg(uint64_t offset, uint64_t value)
{
  volatile uint64_t *addr_ptr =
      (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
  *addr_ptr = value;
}

static inline uint64_t read_smc_reg(uint64_t offset)
{
  volatile uint64_t *addr_ptr =
      (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
  return *addr_ptr;
}

static inline void write_scratch(uint8_t scratch_num, uint32_t value)
{
  volatile uint32_t *addr =
      (volatile uint32_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0) +
                                       (scratch_num * sizeof(uint64_t)));
  *addr = value;
}

static inline uint32_t read_scratch(uint8_t scratch_num)
{
  volatile uint32_t *addr =
      (volatile uint32_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0) +
                                       (scratch_num * sizeof(uint64_t)));
  return *addr;
}

static inline void write_postcode(uint32_t value) { write_scratch(0, value); }

#endif /* SMC_CPU_CTRL_H */
