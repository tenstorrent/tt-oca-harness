/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// PLL/clock initialization for OROM.
// Uses SMC window to access PLL control registers.
//
// PLL registers are accessed via SMC_LOCAL_BASE_ADDR + offset:
//   +0x3000: CGM_0_STATUS (lock_detect in bit 0)
//   +0x3020: AG_MUX_SELECT (clock mux)
//
// Hardware confirmed present in OCAH (gap summary v3).

#pragma once

#include <stdint.h>
#include <stdbool.h>

// Reference clock frequency (always-on, used when PLL strap is clear).
#define SMU_REF_CLK_FREQ_MHZ 100u

// PLL register offsets relative to SMC base.
#define PLL_CGM_0_STATUS_OFFSET 0x3000u
#define PLL_CGM_2_STATUS_OFFSET 0x3008u
#define PLL_AWM_0_STATUS_OFFSET 0x3014u
#define PLL_AG_MUX_SELECT_OFFSET 0x3020u

// CGM_STATUS.lock_detect is bit 0.
#define PLL_CGM_LOCK_DETECT_MASK 0x1u

// Initialize PLL based on strap and fuse configuration.
//
// If bl0_pll_clk strap is false, returns SMU_REF_CLK_FREQ_MHZ immediately.
// If true, waits for fuse sense completion, reads PLL frequency from fuses,
// polls for PLL lock, and switches the clock mux.
//
// Returns the effective system clock frequency in MHz.
uint16_t pll_init(bool bl0_pll_clk_strap);
