// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Synchronize the release of an async active-low reset into clk_i, with a DFT bypass.
//
// Has the module name, parameter and ports of the PULP common_cells rstgen_bypass and is built
// from prim_sync_reset, so vendored code that instantiates rstgen_bypass gets the prim
// synchronizer cells and the hazard-free reset mux.
//
// rst_no asserts asynchronously with rst_ni and deasserts NumRegs clk_i cycles after rst_ni
// deasserts. While test_mode_i is high, rst_no follows rst_test_mode_ni and init_no is high.

module rstgen_bypass #(
  parameter int unsigned NumRegs = 4  // Synchronizer stages, at least 2.
) (
  input  logic clk_i,  // Destination clock.
  input  logic rst_ni,  // Async reset to synchronize, active-low.
  input  logic rst_test_mode_ni,  // Reset used in test mode, active-low.
  input  logic test_mode_i,  // Test mode, active-high.
  output logic rst_no,  // Synchronized reset, active-low.
  output logic init_no  // Synchronized reset, held high in test mode.
);

  prim_sync_reset #(
    .WIDTH(NumRegs)
  ) u_sync_reset (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_mode_i(test_mode_i),
    .scan_rst_ni(rst_test_mode_ni),
    .sync_rst_no(rst_no)
  );

  assign init_no = test_mode_i | rst_no;

endmodule : rstgen_bypass
