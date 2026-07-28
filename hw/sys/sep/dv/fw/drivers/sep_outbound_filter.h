// SPDX-License-Identifier: Apache-2.0
//
// SEP outbound filter driver.
//
// The SEP outbound filter blocks all transactions by default. Firmware must
// open a window before it can reach the testbench mailbox at 0x8000_0000.
// sep_outbound_filter_init() configures filter 0 for that window.
//
// Register layout (OUTBOUND_FILTER_CTRL_0 @ 0x10A2_0000):
//   +0x00  CONFIG (64b)  start-addr (64b) +0x08   end-addr (64b) +0x10
// CONFIG must be written LAST: it enables the filter once the range is set.

#ifndef SEP_OUTBOUND_FILTER_H
#define SEP_OUTBOUND_FILTER_H

#include <stdint.h>

#define SEP_OUTBOUND_FILTER_BASE 0x10A20000u
#define SEP_OUTBOUND_FILTER_CONFIG 0x00u
#define SEP_OUTBOUND_FILTER_START 0x08u
#define SEP_OUTBOUND_FILTER_END 0x10u

// read_allowed(0) | write_allowed(1) | entry_enabled(4) | allow_ns(8) | allow_burst(24)
#define SEP_OUTBOUND_FILTER_CFG_OPEN 0x0000000101000013ULL
#define SEP_OUTBOUND_FILTER_WIN_START 0x0000000080000000ULL
#define SEP_OUTBOUND_FILTER_WIN_END 0x00000000800000FFULL

static inline void sep_wr64(uintptr_t addr, uint64_t val) {
    *((volatile uint64_t *)addr) = val;
}

// Open outbound filter 0 over the 0x8000_0000 mailbox window. Call before any
// mailbox access.
static inline void sep_outbound_filter_init(void) {
    sep_wr64(SEP_OUTBOUND_FILTER_BASE + SEP_OUTBOUND_FILTER_START, SEP_OUTBOUND_FILTER_WIN_START);
    sep_wr64(SEP_OUTBOUND_FILTER_BASE + SEP_OUTBOUND_FILTER_END, SEP_OUTBOUND_FILTER_WIN_END);
    sep_wr64(SEP_OUTBOUND_FILTER_BASE + SEP_OUTBOUND_FILTER_CONFIG,
             SEP_OUTBOUND_FILTER_CFG_OPEN); // enables last
}

#endif // SEP_OUTBOUND_FILTER_H
