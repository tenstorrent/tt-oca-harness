// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Management Controller Reset Unit Wrap Package
//
//-----------------------------------------------------------------------------

package smc_reset_unit_pkg;

  function automatic int unsigned max(int unsigned a, int unsigned b);
    return a > b ? a : b;
  endfunction

  ///////////////////
  // Reset Control //
  ///////////////////

  typedef struct packed {
    logic force_to_ref_clk_n;
    logic cold_reset_n;
    logic warm_reset_n;
    logic config_state_hold;
    logic critical_signal_hold;
    logic sram_hold;
    logic debug_hold;
  } reset_ctrl_t;

  ////////////////////
  // AXI-Lite Types //
  ////////////////////

  localparam int unsigned NumRegMaps = 2;

  typedef enum logic [NumRegMaps-1:0] {
    RESET_UNIT = 2'd0,
    FLR = 2'd1
  } select_t;

endpackage
