// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP scratch-cold register driver (EL2 host side).
//
// The SEP system CSR block has an 8-word "cold" scratch register array (each
// word's [31:0] is software RW) that survives a KM/CPU warm reset. Firmware uses
// it to publish a measured summary to a passive testbench observer that cannot
// run an AXI master while the EL2 owns the LSU bus. Addresses come from
// generated sep_addr.h (via sep.h).

#ifndef SEP_SCRATCH_DRV_H
#define SEP_SCRATCH_DRV_H

#include <stdint.h>

#include "sep.h"

#define SEP_SCRATCH_COLD_BASE OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)
#define SEP_SCRATCH_COLD_STRIDE \
    (OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1) - \
     OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0))

static inline uint32_t sep_scratch_addr(uint32_t idx) {
    return OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(idx);
}

static inline void sep_scratch_wr(uint32_t idx, uint32_t value) {
    *(volatile uint32_t *)sep_scratch_addr(idx) = value;
}

static inline uint32_t sep_scratch_rd(uint32_t idx) {
    return *(volatile uint32_t *)sep_scratch_addr(idx);
}

#endif // SEP_SCRATCH_H
