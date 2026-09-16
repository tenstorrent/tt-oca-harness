// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OCAH shim replacing upstream tt_hw_debug's dependencies/common/generic_clkgate.sv,
// which is an identical latch-and-AND ICG under a different name. Routing it to
// prim_clkgater keeps one clock gate in the design and lets the DFD inherit the
// och_prim_generic `not(synth)` tech swap instead of synthesising a behavioural
// latch. generic_ccg and generic_ipx_clk_rst_ctrl pick this up automatically.
module generic_clkgate (
  input  logic clk,
  input  logic en,
  input  logic te,
  output logic clk_out
);

  prim_clkgater u_clkgater (
    .i_clk(clk),
    .i_en (en),
    .i_te (te),
    .o_clk(clk_out)
  );

endmodule
