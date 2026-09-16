// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Ring oscillator stage wrappers
//
// entropy_ring_oscillator is a free-running combinational loop. With no
// propagation delay anywhere in it, RTL simulation never advances simulated
// time (see issue #1556): every stage settles within the same delta cycle
// as its input, so the loop re-evaluates forever at a single $time.
//
// Real propagation delay comes from whichever prim_clock_nand2 /
// prim_stdbuf / prim_stdmux2 flavor synthesis binds each stage to, and none
// of those flavors carry a delay parameter: they are swapped in as a group
// per build target (see the generic vs. tech-specific implementations of
// these prims), so every flavor must keep the exact same port list. These
// wrappers keep the one-off simulation delay this ring needs local to
// entropy_source instead of adding a parameter to the shared prims: each
// wraps one stage's unmodified prim instance and adds a #1 delay under
// `ifndef SYNTHESIS`, so synthesis - and every other prim_clock_nand2 /
// prim_stdbuf / prim_stdmux2 consumer - sees the ordinary zero-delay cell.
//--------------------------------------------------

module entropy_ring_nand2_wrapper (
  input  i_A1,
  input  i_A2,
  output o_Y
);
  logic y_cell;

  prim_clock_nand2 u_cell (
    .i_A1 (i_A1),
    .i_A2 (i_A2),
    .o_Y  (y_cell)
  );

`ifndef SYNTHESIS
  assign #1 o_Y = y_cell;
`else
  assign o_Y = y_cell;
`endif
endmodule

module entropy_ring_buf_wrapper (
  input  i_A,
  output o_Y
);
  logic y_cell;

  prim_stdbuf u_cell (
    .i_A (i_A),
    .o_Y (y_cell)
  );

`ifndef SYNTHESIS
  assign #1 o_Y = y_cell;
`else
  assign o_Y = y_cell;
`endif
endmodule

module entropy_ring_mux2_wrapper (
  input  i_I0,
  input  i_I1,
  input  i_SEL,
  output o_Y
);
  logic y_cell;

  prim_stdmux2 u_cell (
    .i_I0  (i_I0),
    .i_I1  (i_I1),
    .i_SEL (i_SEL),
    .o_Y   (y_cell)
  );

`ifndef SYNTHESIS
  assign #1 o_Y = y_cell;
`else
  assign o_Y = y_cell;
`endif
endmodule
