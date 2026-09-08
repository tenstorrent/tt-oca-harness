// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Auto-Handshake Data Synchronizer
//
//--------------------------------------------------
module prim_sync_data_autohs #(
  parameter int unsigned WIDTH = 1,
  parameter int unsigned DEPTH = 2    // default currently 2 in order to not break existing usage
) (
  input  logic             i_clk_src,
  input  logic             i_reset_src_n,
  input  logic [WIDTH-1:0] i_data,
  input  logic             i_clk_dst,
  input  logic             i_reset_dst_n,
  output logic [WIDTH-1:0] o_data
);

  ////////////////////////////////////////////////////////////////////////////////
  // Module Functionality
  ////////////////////////////////////////////////////////////////////////////////

  logic  clk1_req_ongoing_reg;
  logic  clk1_req_toggle_reg;
  logic  clk1_ack_toggle;
  logic  clk1_ack_toggle_reg;

  logic  clk2_req_ongoing_reg;
  logic  clk2_req_toggle;
  logic  clk2_req_toggle_reg;
  logic  clk2_ack_toggle_reg;


  if (DEPTH == 2) begin : gen_depth_2
    prim_flop_2sync_r sync_req_toggle (
      .i_CK     (i_clk_dst),
      .i_RN     (i_reset_dst_n),
      .i_D      (clk1_req_toggle_reg),
      .o_Q      (clk2_req_toggle)
    );

    prim_flop_2sync_r sync_ack_toggle (
      .i_CK     (i_clk_src),
      .i_RN     (i_reset_src_n),
      .i_D      (clk2_ack_toggle_reg),
      .o_Q      (clk1_ack_toggle)
    );
  end else begin : gen_depth_3
    prim_flop_3sync_r sync_req_toggle (
      .i_CK     (i_clk_dst),
      .i_RN     (i_reset_dst_n),
      .i_D      (clk1_req_toggle_reg),
      .o_Q      (clk2_req_toggle)
    );

    prim_flop_3sync_r sync_ack_toggle (
      .i_CK     (i_clk_src),
      .i_RN     (i_reset_src_n),
      .i_D      (clk2_ack_toggle_reg),
      .o_Q      (clk1_ack_toggle)
    );
  end


  // generate src req
  logic src_req;
  logic o_clk1_ack;
  assign src_req = ~o_clk1_ack;

  always @(posedge i_clk_src) begin
    if (!i_reset_src_n) begin
      clk1_req_ongoing_reg <= 1'b0;
      clk1_req_toggle_reg  <= 1'b0;
      clk1_ack_toggle_reg  <= 1'b0;
    end else if (!clk1_req_ongoing_reg) begin
      clk1_req_ongoing_reg <= src_req;
      clk1_req_toggle_reg  <= clk1_req_toggle_reg ^ src_req;
    end else begin
      clk1_req_ongoing_reg <= ~o_clk1_ack;
      clk1_ack_toggle_reg  <= clk1_ack_toggle;
    end
  end

  assign o_clk1_ack = (clk1_ack_toggle_reg != clk1_ack_toggle);

  logic dst_ack;

  always @(posedge i_clk_dst) begin
    if (!i_reset_dst_n) begin
      clk2_req_ongoing_reg <= 1'b0;
      clk2_req_toggle_reg  <= 1'b0;
      clk2_ack_toggle_reg  <= 1'b0;
    end else if (!clk2_req_ongoing_reg) begin
      clk2_req_ongoing_reg <= (clk2_req_toggle != clk2_req_toggle_reg);
      clk2_req_toggle_reg  <= clk2_req_toggle;
    end else begin
      clk2_req_ongoing_reg <= ~dst_ack;
      clk2_ack_toggle_reg  <= clk2_ack_toggle_reg ^ dst_ack;
    end
  end

  logic o_clk2_req;
  assign o_clk2_req = clk2_req_ongoing_reg;

  // generate dst ack, delayed one clock from o_clk2_req
  always @(posedge i_clk_dst) begin
    if (!i_reset_dst_n) begin
      dst_ack <= 1'b0;
    end else begin
      dst_ack <= o_clk2_req;
    end
  end


  ////

  logic [WIDTH-1:0] clk1_val_reg;

  always @(posedge i_clk_src) begin
    if (!i_reset_src_n) begin
      clk1_val_reg <= WIDTH'(0);
    end else if (!clk1_req_ongoing_reg && src_req) begin
      clk1_val_reg <= i_data;
    end
  end

  logic clk2_val_sample;

  assign clk2_val_sample = !clk2_req_ongoing_reg && (clk2_req_toggle != clk2_req_toggle_reg);

  logic [WIDTH-1:0] clk2_val_reg;

  always @(posedge i_clk_dst) begin
    if (!i_reset_dst_n) begin
      clk2_val_reg <= WIDTH'(0);
    end else if (clk2_val_sample) begin
      clk2_val_reg <= clk1_val_reg;
    end
  end

  assign o_data = clk2_val_reg;


endmodule
