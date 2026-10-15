/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// PLL/clock initialization for OROM.

#pragma once

#include <stdint.h>
#include <stdbool.h>

// Reference clock frequency (always-on, used when PLL strap is clear).
#define SMU_REF_CLK_FREQ_MHZ 100u

// Initialize PLL based on strap and fuse configuration.
//
// If bl0_pll_clk strap is false, returns SMU_REF_CLK_FREQ_MHZ immediately.
// If true, reads the PLL frequency from fuses and calls
// sep_pll_lock_and_select(); blank fuses keep the reference clock.
//
// Returns the effective system clock frequency in MHz.
uint16_t pll_init(bool bl0_pll_clk_strap);

// Wait for the SMC-owned PLL to lock at freq_mhz, switch SEP's sysclk and
// peripheral clock to it, and return the sysclk frequency SEP then runs at, in
// MHz. The weak default touches no hardware and returns SMU_REF_CLK_FREQ_MHZ,
// because the PLL and its clock mux are adopter IP. A build that carries a PLL
// driver overrides it through OCAH_FW_OVERLAY_SOURCES_sep.
uint16_t sep_pll_lock_and_select(uint16_t freq_mhz);
