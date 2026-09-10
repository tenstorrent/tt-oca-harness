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
        .d_i (~sel_i & !sel_clk1),
        .clk_i(clk0_i),
        .set_ni(rst_ni),
        .q_o (sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r sync_clk0 (
        .d_i (~sel_i & !sel_clk1),
        .clk_i(clk0_i),
        .rst_ni(rst_ni),
        .q_o (sel_sync_clk0)
      );
    end
  endgenerate

  // Clock 1 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b1) begin : gen_sync_clk1_selected
      prim_flop_4sync_s sync_clk1 (
        .d_i (sel_i & !sel_clk0),
        .clk_i(clk1_i),
        .set_ni(rst_ni),
        .q_o (sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r sync_clk1 (
        .d_i (sel_i & !sel_clk0),
        .clk_i(clk1_i),
        .rst_ni(rst_ni),
        .q_o (sel_sync_clk1)
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
        .clk_i(inv_clk0),
        .set_ni(rst_ni),
        .d_i (sel_sync_clk0),
        .q_o (sel_clk0)
      );
      prim_dffrxq clk1_sel (
        .clk_i(inv_clk1),
        .rst_ni(rst_ni),
        .d_i (sel_sync_clk1),
        .q_o (sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_dffrxq clk0_sel (
        .clk_i(inv_clk0),
        .rst_ni(rst_ni),
        .d_i (sel_sync_clk0),
        .q_o (sel_clk0)
      );
      prim_dffsxq clk1_sel (
        .clk_i(inv_clk1),
        .set_ni(rst_ni),
        .d_i (sel_sync_clk1),
        .q_o (sel_clk1)
      );
    end
  endgenerate

  prim_clock_nand2 clk0_gate (
    .a1_i(clk0_i),
    .a2_i(sel_clk0),
    .y_o (gated_clk0)
  );

  prim_clock_nand2 clk1_gate (
    .a1_i(clk1_i),
    .a2_i(sel_clk1),
    .y_o (gated_clk1)
  );

  prim_clock_nand2 clk_out_nd (
    .a1_i(gated_clk0),
    .a2_i(gated_clk1),
    .y_o (clk_o)
  );

endmodule
