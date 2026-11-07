// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare register-map select types for the SMC miscellaneous block.
//
// Enumerates the misc register targets the misc wrapper demultiplexes: cold scratch,
// cold-and-warm scratch, chip_config and NDM reset.
// Exposes NumRegMaps for address decode in smc_misc_wrap; the max() helper is unused by
// the SMC RTL.

package smc_misc_pkg;

  function automatic int unsigned max(int unsigned a, int unsigned b);
    return a > b ? a : b;
  endfunction

  localparam int unsigned NumRegMaps = 4;

  typedef enum logic [$clog2(
NumRegMaps
)-1:0] {
    SCRATCH_COLD        = 2'b00,
    SCRATCH_COLD_WARM   = 2'b01,
    CHIP_CONFIG         = 2'b10,
    NDM_RESET           = 2'b11
  } select_e;

endpackage
