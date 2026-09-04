// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Primitive Glitch-Free Clock Mux 2-to-1
//
//--------------------------------------------------
module prim_clock_mux2_gf #(
  parameter bit SelectOnReset = 1'b0  // Which clock is selected on reset
) (
  input  logic clk0_i,
  input  logic clk1_i,
  input  logic rst_ni,
  input  logic sel_i,
  output logic clk_o
);

  logic sel_sync_clk0, sel_sync_clk1;
  logic gated_clk0, gated_clk1;
  logic inv_clk0, inv_clk1;
  logic sel_clk0, sel_clk1;

  // Clock 0 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sync_clk0_selected
      prim_flop_4sync_s sync_clk0 (
        .i_D (~sel_i & !sel_clk1),
        .i_CK(clk0_i),
        .i_SN(rst_ni),
        .o_Q (sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r sync_clk0 (
        .i_D (~sel_i & !sel_clk1),
        .i_CK(clk0_i),
        .i_RN(rst_ni),
        .o_Q (sel_sync_clk0)
      );
    end
  endgenerate

  // Clock 1 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b1) begin : gen_sync_clk1_selected
      prim_flop_4sync_s sync_clk1 (
        .i_D (sel_i & !sel_clk0),
        .i_CK(clk1_i),
        .i_SN(rst_ni),
        .o_Q (sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r sync_clk1 (
        .i_D (sel_i & !sel_clk0),
        .i_CK(clk1_i),
        .i_RN(rst_ni),
        .o_Q (sel_sync_clk1)
      );
    end
  endgenerate

  prim_clock_inv clk0_inv (
    .clk_i(clk0_i),
    .scanmode_i(1'b0),
    .clk_no(inv_clk0)
  );

  prim_clock_inv clk1_inv (
    .clk_i(clk1_i),
    .scanmode_i(1'b0),
    .clk_no(inv_clk1)
  );

  // Clock selection flops - reset behavior based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sel_clk0_selected
      prim_dffsxq clk0_sel (
        .i_CK(inv_clk0),
        .i_SN(rst_ni),
        .i_D (sel_sync_clk0),
        .o_Q (sel_clk0)
      );
      prim_dffrxq clk1_sel (
        .i_CK(inv_clk1),
        .i_RN(rst_ni),
        .i_D (sel_sync_clk1),
        .o_Q (sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_dffrxq clk0_sel (
        .i_CK(inv_clk0),
        .i_RN(rst_ni),
        .i_D (sel_sync_clk0),
        .o_Q (sel_clk0)
      );
      prim_dffsxq clk1_sel (
        .i_CK(inv_clk1),
        .i_SN(rst_ni),
        .i_D (sel_sync_clk1),
        .o_Q (sel_clk1)
      );
    end
  endgenerate

  prim_clock_nand2 clk0_gate (
    .i_A1(clk0_i),
    .i_A2(sel_clk0),
    .o_Y (gated_clk0)
  );

  prim_clock_nand2 clk1_gate (
    .i_A1(clk1_i),
    .i_A2(sel_clk1),
    .o_Y (gated_clk1)
  );

  prim_clock_nand2 clk_out_nd (
    .i_A1(gated_clk0),
    .i_A2(gated_clk1),
    .o_Y (clk_o)
  );

endmodule
