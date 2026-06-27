// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//--------------------------------------------------
// Reset Bypass Standard Mux 2
//
//--------------------------------------------------
 module prim_rstbypass_stdmux2 (
    input  logic i_reset_n,
    input  logic i_test_reset_n,
    input  logic i_test_mode,
    output logic o_reset_n
);

  prim_stdmux2 rst_bypassmux (
      .i_I0 (i_reset_n),
      .i_I1 (i_test_reset_n),
      .i_SEL(i_test_mode),
      .o_Y  (o_reset_n)
  );

endmodule
