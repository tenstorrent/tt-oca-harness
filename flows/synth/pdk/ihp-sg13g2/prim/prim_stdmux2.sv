// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Select one of two inputs.
//
// Maps to one sg13g2_mux2_1.
module prim_stdmux2 (
  input  logic i0_i,  // Input selected while sel_i is low.
  input  logic i1_i,  // Input selected while sel_i is high.
  input  logic sel_i,  // Input select.
  output logic y_o  // Selected input.
);
  (* dont_touch = "true" *)
  sg13g2_mux2_1 u_cell (
    .A0      (i0_i),
    .A1      (i1_i),
    .S       (sel_i),
    .X       (y_o)
  );
endmodule
