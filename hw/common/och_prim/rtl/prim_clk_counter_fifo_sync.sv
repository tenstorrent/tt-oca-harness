// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Counter FIFO Sync
//
//--------------------------------------------------
module prim_clk_counter_fifo_sync #(
  parameter int unsigned CLOCK_COUNTER_WIDTH = 64
) (
  input  logic                            ref_clk_i,
  input  logic                            ref_clk_rst_ni,
  input  logic                            ref_clk_done_i,
  input  logic                            tile_rst_ni,
  input  logic                            ss_clk_i,
  input  logic                            ss_rst_ni,

  input  logic                            clk_count_en_i,
  input  logic                            clk_i,
  output logic                            clk_count_valid_o,
  output logic [CLOCK_COUNTER_WIDTH-1:0]  clk_counts_o
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
  ) u_clk_counter (
    .refclk_i(ref_clk_i),
    .refclk_cnt_done_i(ref_clk_done_i),
    .refclk_rst_ni(ref_clk_rst_ni),

    .clk_i(clk_i),
    .rst_ni(tile_rst_ni),

    .test_mode_i('0),
    .scan_rst_ni('0),

    .cnt_en_i(clk_count_en_i),
    .clk_cnt_o(clock_count),
    .clk_cnt_valid_o(clock_count_valid)
  );

  prim_sync_reset u_prim_pll_sync_reset (
    .clk_i(clk_i),
    .rst_ni(tile_rst_ni),
    .test_mode_i('0),
    .scan_rst_ni('0),
    .sync_rst_no(tile_reset_n_sync)
  );

  wire combined_reset_n = tile_rst_ni & ss_rst_ni;

  prim_sync_reset u_prim_pll_combined_sync_reset (
    .clk_i(clk_i),
    .rst_ni(combined_reset_n),
    .test_mode_i('0),
    .scan_rst_ni('0),
    .sync_rst_no(combined_tile_reset_n_sync)
  );

  prim_sync_reset u_ss_combined_sync_reset (
    .clk_i(ss_clk_i),
    .rst_ni(combined_reset_n),
    .test_mode_i('0),
    .scan_rst_ni('0),
    .sync_rst_no(combined_ss_reset_n_sync)
  );

  always_ff @(posedge clk_i) begin
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
  ) u_prim_fifo_async (
    .clk_wr_i(clk_i),
    .rst_wr_ni(combined_tile_reset_n_sync),
    .wvalid_i(valid_update),
    .wready_o(),    // unused
    .wdata_i({clock_count_valid, clock_count}),
    .wdepth_o(),    // unused

    .clk_rd_i(ss_clk_i),
    .rst_rd_ni(combined_ss_reset_n_sync),
    .rvalid_o(clock_count_valid_we),
    .rready_i(clock_count_valid_we), // pop immediately when valid
    .rdata_o({clk_count_valid_sync, clk_counts_sync}),
    .rdepth_o()     // unused
  );

  always_ff @(posedge ss_clk_i) begin
    if (!ss_rst_ni) begin
      clk_count_valid_o <= '0;
      clk_counts_o      <= '0;
    end else begin
      clk_count_valid_o <= clock_count_valid_we ? clk_count_valid_sync : clk_count_valid_o;
      clk_counts_o      <= clock_count_valid_we ? clk_counts_sync      : clk_counts_o;
    end
  end

endmodule
