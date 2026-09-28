// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mux two active-low resets without a static-1 hazard on select changes.
//
// Drive rst_no as sel_i ? rst1_ni : rst0_ni, with the AO222 consensus term (rst0_ni &
// rst1_ni) suppressing the static-1 hazard that would otherwise let a change of sel_i assert
// rst_no while both inputs hold it deasserted.
//
// Only sel_i may change while the data inputs are live. If sel_i and a data input change
// together, sel_i arriving first leaves all three product terms at 0 and rst_no glitches, so
// the driver must settle rst0_ni and rst1_ni before moving sel_i.

module prim_rst_mux2_hf_n (
  input  logic rst0_ni,  // Active-low reset selected when sel_i is low.
  input  logic rst1_ni,  // Active-low reset selected when sel_i is high.
  input  logic sel_i,  // Selects rst1_ni when high; must change only after rst0_ni and rst1_ni
                       // settle.
  output logic rst_no  // Hazard-free muxed reset, active-low.
);

  logic sel_n;

  prim_inv u_sel_inv (
    .in_i (sel_i),
    .out_o(sel_n)
  );

  prim_ao222 u_mux (
    .a0_i (rst1_ni),
    .a1_i (sel_i),
    .b0_i (rst0_ni),
    .b1_i (sel_n),
    .c0_i (rst0_ni),
    .c1_i (rst1_ni),
    .out_o(rst_no)
  );

endmodule
