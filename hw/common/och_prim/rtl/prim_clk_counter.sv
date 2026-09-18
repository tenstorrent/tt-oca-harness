// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Counter
//
//--------------------------------------------------
module prim_clk_counter #(
  parameter int unsigned WIDTH = 24
) (
  input  logic             refclk_i,
  input  logic             refclk_cnt_done_i,
  input  logic             refclk_rst_ni,
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic             test_mode_i,
  input  logic             scan_rst_ni,
  input  logic             cnt_en_i,
  output logic [WIDTH-1:0] clk_cnt_o,
  output logic             clk_cnt_valid_o
);

  wire reset_n_synced;
  wire cnt_en_synced;
  wire cnt_done_synced;

  prim_sync_reset #(
    .WIDTH(4)
  ) sync_reset_n (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .test_mode_i(test_mode_i),
    .scan_rst_ni(scan_rst_ni),
    .sync_rst_no(reset_n_synced)
  );

  reg  cnt_en_d;
  reg  cnt_en_valid;
  wire cnt_en_src_ready;
  reg  cnt_en_synced_d;
  wire cnt_en_sync_valid;
  wire cnt_start_synced;

  always_ff @(posedge refclk_i) begin
    if (!refclk_rst_ni) begin
      cnt_en_d     <= 1'b0;
      cnt_en_valid <= 1'b0;
    end else begin
      cnt_en_d <= cnt_en_i;

      // If a change is detected on cnt_en_i, assert valid to start a transfer.
      if (cnt_en_d ^ cnt_en_i) begin
        cnt_en_valid <= 1'b1;
        // If the transfer has been acknowledged, de-assert valid.
      end else if (cnt_en_src_ready) begin
        cnt_en_valid <= 1'b0;
      end
    end
  end

  cdc_4phase sync_cnt_en (
    .src_rst_ni  (refclk_rst_ni),
    .src_clk_i   (refclk_i),
    .src_data_i  (cnt_en_d),
    .src_valid_i (cnt_en_valid),
    .src_ready_o (cnt_en_src_ready),

    .dst_rst_ni  (reset_n_synced),
    .dst_clk_i   (clk_i),
    .dst_data_o  (cnt_en_synced),
    .dst_valid_o (cnt_en_sync_valid),
    .dst_ready_i (1'b1)
  );

  always_ff @(posedge clk_i) begin
    if (!reset_n_synced) begin
      cnt_en_synced_d <= 1'b0;
    end else begin
      cnt_en_synced_d <= cnt_en_sync_valid ? cnt_en_synced : cnt_en_synced_d;
    end
  end
  assign cnt_start_synced = ~cnt_en_synced_d & cnt_en_synced;

  prim_sync3_pulse sync_refclk_cnt_done (
    .src_pulse_i(refclk_cnt_done_i),
    .src_clk_i(refclk_i),
    .src_rst_ni(refclk_rst_ni),
    .dst_clk_i(clk_i),
    .dst_pulse_o(cnt_done_synced)
  );

  reg [WIDTH-1:0] clk_cnt;

  always_ff @(posedge clk_i) begin
    if (~reset_n_synced | ~cnt_en_synced) begin
      clk_cnt <= WIDTH'(0);
    end else begin
      clk_cnt <= cnt_done_synced ? WIDTH'(0) : &clk_cnt ? clk_cnt : clk_cnt + WIDTH'(1);
    end
  end

  always_ff @(posedge clk_i) begin
    if (~reset_n_synced) begin
      clk_cnt_o <= WIDTH'(0);
      clk_cnt_valid_o <= 1'b0;
    end else begin
      clk_cnt_o <= cnt_done_synced ? clk_cnt : clk_cnt_o;
      clk_cnt_valid_o <= cnt_en_synced ? (cnt_done_synced ? 1'b1 : (cnt_start_synced ? 1'b0 : clk_cnt_valid_o)) : 1'b0;
    end
  end

endmodule
