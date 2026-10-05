// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OCAH shim replacing upstream tt_hw_debug's dependencies/common/generic_clkmux2.sv.
module generic_clkmux2 (
  input  logic in0,
  input  logic in1,
  input  logic select,
  output logic out
);

  prim_clock_mux2 u_clock_mux2 (
    .clk0_i(in0),
    .clk1_i(in1),
    .sel_i (select),
    .clk_o (out)
  );

endmodule
