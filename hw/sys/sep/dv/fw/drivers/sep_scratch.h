// SPDX-License-Identifier: Apache-2.0
//
// SEP scratch-cold register driver (EL2 host side).
//
// The SEP system CSR block has an 8-word "cold" scratch register array (each
// word's [31:0] is software RW) that survives a KM/CPU warm reset. Firmware uses
// it to publish a measured summary to a passive testbench observer that cannot
// run an AXI master while the EL2 owns the LSU bus. (Addresses are SEP fabric
// facts; meta/registers sep_scratch. Cold base = 0x1080_2000, 8-byte stride.)

#ifndef SEP_SCRATCH_H
#define SEP_SCRATCH_H

#include <stdint.h>

#define SEP_SCRATCH_COLD_BASE   0x10802000u  // SCRATCH[0]; stride 8 bytes
#define SEP_SCRATCH_COLD_STRIDE 0x8u

static inline uint32_t sep_scratch_addr(uint32_t idx)
{
    return SEP_SCRATCH_COLD_BASE + idx * SEP_SCRATCH_COLD_STRIDE;
}

static inline void sep_scratch_wr(uint32_t idx, uint32_t value)
{
    *(volatile uint32_t *)sep_scratch_addr(idx) = value;
}

static inline uint32_t sep_scratch_rd(uint32_t idx)
{
    return *(volatile uint32_t *)sep_scratch_addr(idx);
}

#endif  // SEP_SCRATCH_H
