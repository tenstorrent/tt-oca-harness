// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// OCAH shim replacing upstream tt_hw_debug's dependencies/common/generic_clkmux2.sv.
// Its only instance is the test-reset override mux inside generic_ipx_clk_rst_ctrl,
// so this maps to prim_stdmux2 (a plain 2:1 select) rather than prim_clock_mux2,
// which is a clock mux and wrong for a reset path.
module generic_clkmux2 (
    input  logic in0,
    input  logic in1,
    input  logic select,
    output logic out
);

  prim_stdmux2 #(
      .Width(1)
  ) u_stdmux2 (
      .i_I0 (in0),
      .i_I1 (in1),
      .i_SEL(select),
      .o_Y  (out)
  );

endmodule
