// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare register-map select types for the SMC miscellaneous block.
//
// Enumerates the misc register targets the misc wrapper demultiplexes: cold scratch,
// cold-and-warm scratch, chip_config, NDM reset and the error slave.
// Exposes NumRegMaps for address decode in smc_misc_wrap; the max() helper is unused by
// the SMC RTL.

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
  } select_e;

endpackage
