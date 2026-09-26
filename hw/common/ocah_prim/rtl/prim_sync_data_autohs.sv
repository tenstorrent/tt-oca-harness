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
  input  logic             clk_src_i,
  input  logic             rst_src_ni,
  input  logic [WIDTH-1:0] data_i,
  input  logic             clk_dst_i,
  input  logic             rst_dst_ni,
  output logic [WIDTH-1:0] data_o
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
    prim_flop_2sync #(
      .Width(1)
    ) u_sync_req_toggle (
      .clk_i (clk_dst_i),
      .rst_ni(rst_dst_ni),
      .d_i   (clk1_req_toggle_reg),
      .q_o   (clk2_req_toggle)
    );

    prim_flop_2sync #(
      .Width(1)
    ) u_sync_ack_toggle (
      .clk_i (clk_src_i),
      .rst_ni(rst_src_ni),
      .d_i   (clk2_ack_toggle_reg),
      .q_o   (clk1_ack_toggle)
    );
  end else begin : gen_depth_3
    prim_flop_3sync_r u_sync_req_toggle (
      .clk_i (clk_dst_i),
      .rst_ni(rst_dst_ni),
      .d_i   (clk1_req_toggle_reg),
      .q_o   (clk2_req_toggle)
    );

    prim_flop_3sync_r u_sync_ack_toggle (
      .clk_i (clk_src_i),
      .rst_ni(rst_src_ni),
      .d_i   (clk2_ack_toggle_reg),
      .q_o   (clk1_ack_toggle)
    );
  end


  // generate src req
  logic src_req;
  logic o_clk1_ack;
  assign src_req = ~o_clk1_ack;

  always @(posedge clk_src_i) begin
    if (!rst_src_ni) begin
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

  always @(posedge clk_dst_i) begin
    if (!rst_dst_ni) begin
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
  always @(posedge clk_dst_i) begin
    if (!rst_dst_ni) begin
      dst_ack <= 1'b0;
    end else begin
      dst_ack <= o_clk2_req;
    end
  end


  ////

  logic [WIDTH-1:0] clk1_val_reg;

  always @(posedge clk_src_i) begin
    if (!rst_src_ni) begin
      clk1_val_reg <= WIDTH'(0);
    end else if (!clk1_req_ongoing_reg && src_req) begin
      clk1_val_reg <= data_i;
    end
  end

  logic clk2_val_sample;

  assign clk2_val_sample = !clk2_req_ongoing_reg && (clk2_req_toggle != clk2_req_toggle_reg);

  logic [WIDTH-1:0] clk2_val_reg;

  always @(posedge clk_dst_i) begin
    if (!rst_dst_ni) begin
      clk2_val_reg <= WIDTH'(0);
    end else if (clk2_val_sample) begin
      clk2_val_reg <= clk1_val_reg;
    end
  end

  assign data_o = clk2_val_reg;


endmodule
