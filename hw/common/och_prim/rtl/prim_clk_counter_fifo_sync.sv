// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Counter FIFO Sync
//
//--------------------------------------------------
module prim_clk_counter_fifo_sync #(
  parameter int unsigned CLOCK_COUNTER_WIDTH = 64
) (
  input  logic                            i_ref_clk,
  input  logic                            i_ref_clk_reset_n,
  input  logic                            i_ref_clk_done,
  input  logic                            i_tile_reset_n,
  input  logic                            i_ss_clk,
  input  logic                            i_ss_reset_n,

  input  logic                            i_clk_count_en,
  input  logic                            i_clk,
  output logic                            o_clk_count_valid,
  output logic [CLOCK_COUNTER_WIDTH-1:0]  o_clk_counts
);

  logic [CLOCK_COUNTER_WIDTH-1:0] clock_count;
  logic                           clock_count_valid;
  logic                           clock_count_valid_q;
  logic                           clock_count_valid_we;
  logic                           tile_reset_n_sync;
  logic                           combined_tile_reset_n_sync;
  logic                           combined_ss_reset_n_sync;
  logic                           valid_update;

  logic                           clk_count_valid_sync;
  logic [CLOCK_COUNTER_WIDTH-1:0] clk_counts_sync;

  prim_clk_counter #(
    .WIDTH(CLOCK_COUNTER_WIDTH)
  ) clk_counter (
    .i_refclk(i_ref_clk),
    .i_refclk_cnt_done(i_ref_clk_done),
    .i_refclk_reset_n(i_ref_clk_reset_n),

    .i_clk(i_clk),
    .i_reset_n(i_tile_reset_n),

    .i_test_mode('0),
    .i_scan_rst_n('0),

    .i_cnt_en(i_clk_count_en),
    .o_clk_cnt(clock_count),
    .o_clk_cnt_valid(clock_count_valid)
  );

  prim_sync_reset prim_pll_sync_reset (
    .clk(i_clk),
    .rst_n(i_tile_reset_n),
    .test_mode('0),
    .scan_rst_n('0),
    .sync_rst_n(tile_reset_n_sync)
  );

  wire combined_reset_n = i_tile_reset_n & i_ss_reset_n;

  prim_sync_reset prim_pll_combined_sync_reset (
    .clk(i_clk),
    .rst_n(combined_reset_n),
    .test_mode('0),
    .scan_rst_n('0),
    .sync_rst_n(combined_tile_reset_n_sync)
  );

  prim_sync_reset ss_combined_sync_reset (
    .clk(i_ss_clk),
    .rst_n(combined_reset_n),
    .test_mode('0),
    .scan_rst_n('0),
    .sync_rst_n(combined_ss_reset_n_sync)
  );

  always_ff @(posedge i_clk) begin
    if (!tile_reset_n_sync) begin
      clock_count_valid_q <= 1'b0;
    end else begin
      clock_count_valid_q <= clock_count_valid;
    end
  end
  assign valid_update = clock_count_valid_q ^ clock_count_valid;

  prim_fifo_async #(
    .Width(CLOCK_COUNTER_WIDTH + 1),
    .Depth(1)
  ) prim_fifo_async (
    .clk_wr_i(i_clk),
    .rst_wr_ni(combined_tile_reset_n_sync),
    .wvalid_i(valid_update),
    .wready_o(),    // unused
    .wdata_i({clock_count_valid, clock_count}),
    .wdepth_o(),    // unused

    .clk_rd_i(i_ss_clk),
    .rst_rd_ni(combined_ss_reset_n_sync),
    .rvalid_o(clock_count_valid_we),
    .rready_i(clock_count_valid_we), // pop immediately when valid
    .rdata_o({clk_count_valid_sync, clk_counts_sync}),
    .rdepth_o()     // unused
  );

  always_ff @(posedge i_ss_clk) begin
    if (!i_ss_reset_n) begin
      o_clk_count_valid <= '0;
      o_clk_counts      <= '0;
    end else begin
      o_clk_count_valid <= clock_count_valid_we ? clk_count_valid_sync : o_clk_count_valid;
      o_clk_counts      <= clock_count_valid_we ? clk_counts_sync      : o_clk_counts;
    end
  end

endmodule
