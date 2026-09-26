// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Count clk_i edges while a reference window on refclk_i is open.
//
// Close the window on refclk_cnt_done_i and make clk_cnt_o valid; the counter restarts from
// zero at each window end and saturates at all ones.
// test_mode_i swaps scan_rst_ni onto the reset path.
// cnt_en_i must be high for the counter to run; it crosses from refclk_i to clk_i through a
// 4-phase handshake, and refclk_cnt_done_i through a toggle pulse synchronizer.

module prim_clk_counter #(
  parameter int unsigned WIDTH = 24  // Counter width.
) (
  input  logic             refclk_i,  // Reference clock for the measurement window.
  input  logic             refclk_cnt_done_i,  // Single-cycle pulse on refclk_i that ends each
                                               // window.
  input  logic             refclk_rst_ni,  // Active-low reset for the refclk_i-side logic and both
                                           // CDC source sides.
  input  logic             clk_i,  // Clock under measurement.
  input  logic             rst_ni,  // Active-low reset for the clk_i domain; asserts
                                    // asynchronously, deasserts after four clk_i cycles.
  input  logic             test_mode_i,  // Selects scan_rst_ni on the reset mux.
  input  logic             scan_rst_ni,  // DFT scan reset, active-low.
  input  logic             cnt_en_i,  // Enables counting; in the refclk_i domain. Low clears the
                                      // count and clk_cnt_valid_o.
  output logic [WIDTH-1:0] clk_cnt_o,  // clk_i cycles counted in the last closed window.
  output logic             clk_cnt_valid_o  // clk_cnt_o is valid after the window closes.
);

  wire reset_n_synced;
  wire cnt_en_synced;
  wire cnt_done_synced;

  prim_sync_reset #(
    .WIDTH(4)
  ) u_sync_reset_n (
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

  cdc_4phase u_sync_cnt_en (
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

  prim_sync3_pulse u_sync_refclk_cnt_done (
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
