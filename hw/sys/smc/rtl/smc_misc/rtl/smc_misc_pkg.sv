// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Management Controller Miscellaneous Package
//
//-----------------------------------------------------------------------------

package smc_misc_pkg;

  function automatic int unsigned max(int unsigned a, int unsigned b);
    return a > b ? a : b;
  endfunction

  localparam int unsigned NumRegMaps = 5;

  typedef enum logic [$clog2(
NumRegMaps
)-1:0] {
    SCRATCH_COLD        = 3'b000,
    SCRATCH_COLD_WARM   = 3'b001,
    CHIP_CONFIG         = 3'b010,
    NDM_RESET           = 3'b011,
    ERR_SLV             = 3'b100
  } select_t;

endpackage
