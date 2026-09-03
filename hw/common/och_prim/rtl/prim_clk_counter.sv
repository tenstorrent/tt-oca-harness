// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Counter
//
//--------------------------------------------------
module prim_clk_counter #(
  parameter int unsigned WIDTH = 24
) (
  input  logic             i_refclk,
  input  logic             i_refclk_cnt_done,
  input  logic             i_refclk_reset_n,
  input  logic             i_clk,
  input  logic             i_reset_n,
  input  logic             i_test_mode,
  input  logic             i_scan_rst_n,
  input  logic             i_cnt_en,
  output logic [WIDTH-1:0] o_clk_cnt,
  output logic             o_clk_cnt_valid
);

  wire reset_n_synced;
  wire cnt_en_synced;
  wire cnt_done_synced;

  prim_sync_reset #(
    .WIDTH(4)
  ) sync_reset_n (
    .clk(i_clk),
    .rst_n(i_reset_n),
    .test_mode(i_test_mode),
    .scan_rst_n(i_scan_rst_n),
    .sync_rst_n(reset_n_synced)
  );

  reg  cnt_en_d;
  reg  cnt_en_valid;
  wire cnt_en_src_ready;
  reg  cnt_en_synced_d;
  wire cnt_en_sync_valid;
  wire cnt_start_synced;

  always_ff @(posedge i_refclk) begin
    if (!i_refclk_reset_n) begin
      cnt_en_d     <= 1'b0;
      cnt_en_valid <= 1'b0;
    end else begin
      cnt_en_d <= i_cnt_en;

      // If a change is detected on i_cnt_en, assert valid to start a transfer.
      if (cnt_en_d ^ i_cnt_en) begin
        cnt_en_valid <= 1'b1;
        // If the transfer has been acknowledged, de-assert valid.
      end else if (cnt_en_src_ready) begin
        cnt_en_valid <= 1'b0;
      end
    end
  end

  cdc_4phase sync_cnt_en (
    .src_rst_ni  (i_refclk_reset_n),
    .src_clk_i   (i_refclk),
    .src_data_i  (cnt_en_d),
    .src_valid_i (cnt_en_valid),
    .src_ready_o (cnt_en_src_ready),

    .dst_rst_ni  (reset_n_synced),
    .dst_clk_i   (i_clk),
    .dst_data_o  (cnt_en_synced),
    .dst_valid_o (cnt_en_sync_valid),
    .dst_ready_i (1'b1)
  );

  always_ff @(posedge i_clk) begin
    if (!reset_n_synced) begin
      cnt_en_synced_d <= 1'b0;
    end else begin
      cnt_en_synced_d <= cnt_en_sync_valid ? cnt_en_synced : cnt_en_synced_d;
    end
  end
  assign cnt_start_synced = ~cnt_en_synced_d & cnt_en_synced;

  prim_sync3_pulse sync_refclk_cnt_done (
    .i_src_pulse(i_refclk_cnt_done),
    .i_src_clk(i_refclk),
    .i_src_reset_n(i_refclk_reset_n),
    .i_dst_clk(i_clk),
    .o_dst_pulse(cnt_done_synced)
  );

  reg [WIDTH-1:0] clk_cnt;

  always_ff @(posedge i_clk) begin
    if (~reset_n_synced | ~cnt_en_synced) begin
      clk_cnt <= WIDTH'(0);
    end else begin
      clk_cnt <= cnt_done_synced ? WIDTH'(0) : &clk_cnt ? clk_cnt : clk_cnt + WIDTH'(1);
    end
  end

  always_ff @(posedge i_clk) begin
    if (~reset_n_synced) begin
      o_clk_cnt <= WIDTH'(0);
      o_clk_cnt_valid <= 1'b0;
    end else begin
      o_clk_cnt <= cnt_done_synced ? clk_cnt : o_clk_cnt;
      o_clk_cnt_valid <= cnt_en_synced ? (cnt_done_synced ? 1'b1 : (cnt_start_synced ? 1'b0 : o_clk_cnt_valid)) : 1'b0;
    end
  end

endmodule
