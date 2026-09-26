// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap ring-oscillator stage primitives with simulation-only propagation delay.
//
// entropy_ring_oscillator is a free-running combinational loop; without delay, RTL
// simulation never advances time because every stage settles in the same delta cycle.
//
// Real delay comes from whichever prim_clock_nand2 / prim_stdbuf / prim_stdmux2 flavor
// synthesis binds; those prims cannot grow a delay parameter without breaking every other
// consumer. Each wrapper instances an unmodified prim and adds #1 delay under
// `ifndef SYNTHESIS` so synthesis and other consumers see zero-delay cells.

module entropy_ring_nand2_wrapper (
  input  a1_i,                          // First NAND input.
  input  a2_i,                          // Second NAND input.
  output y_o                            // Cell output.
);
  logic y_cell;

  prim_clock_nand2 u_cell (
    .a1_i (a1_i),
    .a2_i (a2_i),
    .y_o  (y_cell)
  );

`ifndef SYNTHESIS
  assign #1 y_o = y_cell;
`else
  assign y_o = y_cell;
`endif
endmodule

module entropy_ring_buf_wrapper (
  input  a_i,                           // Buffer or mux data input
  output y_o                            // Cell output
);
  logic y_cell;

  prim_stdbuf u_cell (
    .a_i (a_i),
    .y_o (y_cell)
  );

`ifndef SYNTHESIS
  assign #1 y_o = y_cell;
`else
  assign y_o = y_cell;
`endif
endmodule

module entropy_ring_mux2_wrapper (
  input  i0_i,                          // I0
  input  i1_i,                          // I1
  input  sel_i,                         // Sel
  output y_o                            // Cell output
);
  logic y_cell;

  prim_stdmux2 u_cell (
    .i0_i  (i0_i),
    .i1_i  (i1_i),
    .sel_i (sel_i),
    .y_o   (y_cell)
  );

`ifndef SYNTHESIS
  assign #1 y_o = y_cell;
`else
  assign y_o = y_cell;
`endif
endmodule
