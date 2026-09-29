// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap ring-oscillator stage primitives with simulation-only propagation delay.
//
// entropy_ring_oscillator is a free-running combinational loop; without delay, RTL
// simulation never advances time because every stage settles in the same delta cycle.
//
// Real delay comes from whichever prim_clock_nand2 / prim_buf / prim_stdmux2 flavor
// synthesis binds each stage to. The generic and technology-specific flavors are swapped
// in as a group per build target, so every flavor keeps the same port list and none
// carries a delay parameter. Each wrapper instances one unmodified prim and adds a #1
// delay only when neither SYNTHESIS nor EMULATION is defined, so synthesis, emulation and
// every other consumer of those prims see the ordinary zero-delay cell. In the emulation
// view the ring is a zero-delay combinational loop that the emulator compile must break
// or model.

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

`ifdef EMULATION
  assign y_o = y_cell;
`elsif SYNTHESIS
  assign y_o = y_cell;
`else
  assign #1 y_o = y_cell;
`endif
endmodule

module entropy_ring_buf_wrapper (
  input  a_i,                           // Buffer data input.
  output y_o                            // Cell output.
);
  logic y_cell;

  prim_buf u_cell (
    .in_i (a_i),
    .out_o(y_cell)
  );

`ifdef EMULATION
  assign y_o = y_cell;
`elsif SYNTHESIS
  assign y_o = y_cell;
`else
  assign #1 y_o = y_cell;
`endif
endmodule

module entropy_ring_mux2_wrapper (
  input  i0_i,                          // Data driven onto y_o while sel_i is low.
  input  i1_i,                          // Data driven onto y_o while sel_i is high.
  input  sel_i,                         // Input select: high picks i1_i, low picks i0_i.
  output y_o                            // Cell output.
);
  logic y_cell;

  prim_stdmux2 u_cell (
    .i0_i  (i0_i),
    .i1_i  (i1_i),
    .sel_i (sel_i),
    .y_o   (y_cell)
  );

`ifdef EMULATION
  assign y_o = y_cell;
`elsif SYNTHESIS
  assign y_o = y_cell;
`else
  assign #1 y_o = y_cell;
`endif
endmodule
