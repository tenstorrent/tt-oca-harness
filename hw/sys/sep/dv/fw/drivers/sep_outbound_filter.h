// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP outbound filter driver. Header-only.
//
// The outbound filter blocks all transactions by default. Firmware must open a
// window before it can reach the testbench mailbox (STDOUT in tb.h).
// sep_outbound_filter_init() configures filter 0 for that window.
//
// Addresses come from generated sep_addr.h; FILTER_CONFIG packing uses
// generated filter_ctrl.h field masks (same pattern as sep_spi.h / sep_dma.h).

#ifndef SEP_OUTBOUND_FILTER_H
#define SEP_OUTBOUND_FILTER_H

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "smc_sep_xbar_protocol.h"
#include "tb.h"
#include "filter_ctrl.h"

/*
 * FILTER_CONFIG open window. XBAR_SEP_OUTBOUND_CFG is the named golden
 * for the same word: read | write | entry_enabled | allow_burst, with the
 * read-only data_bus_width at its reset value and no bit set outside a
 * field. Do NOT set ALLOW_NS: EN_NS_FILTER=1 and SEP CPU traffic is secure
 * (ns=0).
 */
#define SEP_OUTBOUND_FILTER_CFG_OPEN XBAR_SEP_OUTBOUND_CFG

_Static_assert(SEP_OUTBOUND_FILTER_CFG_OPEN ==
                   (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm |
                    FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm |
                    FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm |
                    FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm |
                    ((unsigned long long)FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset
                     << FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp)),
               "XBAR_SEP_OUTBOUND_CFG does not match the filter_ctrl.rdl field layout");

/* Mailbox window: STDOUT (test_completion) plus a small pad. */
#define SEP_OUTBOUND_FILTER_WIN_START ((uint64_t)(uint32_t)STDOUT)
#define SEP_OUTBOUND_FILTER_WIN_END (((uint64_t)(uint32_t)STDOUT) + 0xFFULL)

/*
 * Open filter 0 over [start, end]. Write START/END before CONFIG so the
 * filter enables atomically over the final range.
 */
static inline void sep_outbound_filter_init_range(uint64_t start, uint64_t end) {
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0), start);
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0), end);
    WRITE_REG64(SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0),
                SEP_OUTBOUND_FILTER_CFG_OPEN);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Open filter 0 over the testpass mailbox window. Call before mailbox access. */
static inline void sep_outbound_filter_init(void) {
    sep_outbound_filter_init_range(SEP_OUTBOUND_FILTER_WIN_START, SEP_OUTBOUND_FILTER_WIN_END);
}

#endif // SEP_OUTBOUND_FILTER_H
