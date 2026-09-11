// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Hazard-Free Active-Low Reset Mux 2-to-1
//
// rst_no = sel_i ? rst1_ni : rst0_ni, with the AO222 consensus term
// (rst0_ni & rst1_ni) suppressing the static-1 hazard that would otherwise
// let a change of sel_i assert rst_no while both inputs hold it deasserted.
//
// Only sel_i may change. If sel_i and a data input change together, sel_i
// arriving first leaves all three product terms at 0 and rst_no glitches, so
// the driver must settle rst0_ni and rst1_ni before moving sel_i.
//--------------------------------------------------
module prim_rst_mux2_hf_n (
  input  logic rst0_ni,
  input  logic rst1_ni,
  input  logic sel_i,
  output logic rst_no
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
