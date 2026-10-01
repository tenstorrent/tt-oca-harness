// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Serialize wr_data_i onto tx_o at the baud tick rate.
// A frame is a low start bit, the data bits LSB first, the optional parity bit and high stop
// bits; the baud tick is every sixteenth tick_baud_x16_i.
//
// wr_i loads a frame from wr_data_i and wr_parity_i using word_length_i, parity_enable_i,
// and extra_stop_bit_i.
// tick_baud_x16_i derives the baud tick; idle_o is high when the shifter is empty or
// tx_enable_i is low.

module uart_tx
  import uart_16550_pkg::*;
#(
) (
  input  logic       clk_i,             // System clock.
  input  logic       rst_ni,            // Async reset, active-low.

  input  logic       tx_enable_i,       // Transmitter enable. Low clears the shifter and holds tx_o
                                        // high.
  input  logic       tick_baud_x16_i,   // 16× baud oversample tick.
  input  logic       parity_enable_i,   // Include a parity bit in the frame.
  input  logic [3:0] word_length_i,     // Data bits per frame, 5 to 8.
  input  logic       extra_stop_bit_i,  // Add a second stop bit when high.

  input  logic       wr_i,              // Pulse that loads wr_data_i into the shifter. A load while
                                        // busy replaces the frame in progress, so assert it only
                                        // while idle_o is high.
  input  logic       wr_parity_i,       // Parity bit loaded with wr_data_i; used only when
                                        // parity_enable_i is high.
  input  logic [7:0] wr_data_i,         // Transmit data byte.
  output logic       idle_o,            // High when the shifter is empty or tx_enable_i is low.

  output logic       tx_o               // Serial transmit line; registered, idles high.
);

  logic  [3:0] baud_div_q;
  logic        tick_baud_q;

  logic [3:0] bit_cnt_q, bit_cnt_d;
  logic [11:0] sreg_q, sreg_d;
  logic tx_d;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      baud_div_q  <= 4'd0;
      tick_baud_q <= 1'b0;
    end else if (tick_baud_x16_i) begin
      {tick_baud_q, baud_div_q} <= {1'b0, baud_div_q} + 5'd1;
    end else begin
      tick_baud_q <= 1'b0;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      bit_cnt_q <= 4'h0;
      sreg_q    <= 12'hfff;
      tx_o      <= 1'b1;
    end else begin
      bit_cnt_q <= bit_cnt_d;
      sreg_q    <= sreg_d;
      tx_o      <= tx_d;
    end
  end

  always_comb begin
    if (!tx_enable_i) begin
      bit_cnt_d = 4'd0;
      sreg_d    = 12'hfff;
      tx_d      = 1'b1;
    end else begin
      bit_cnt_d = bit_cnt_q;
      sreg_d    = sreg_q;
      tx_d      = tx_o;
      if (wr_i) begin
        sreg_d = get_tx_frame_from_data(
                             wr_data_i,
                             wr_parity_i,
                             word_length_i,
                             parity_enable_i
                         );
        bit_cnt_d = get_frame_length(
                                TX,
                                word_length_i,
                                extra_stop_bit_i,
                                parity_enable_i
                            );
      end else if (tick_baud_q && bit_cnt_q != 4'd0) begin
        sreg_d    = {1'h1, sreg_q[11:1]};
        tx_d      = sreg_q[0];
        bit_cnt_d = bit_cnt_q - 4'd1;
      end
    end
  end

  assign idle_o = !tx_enable_i || bit_cnt_q == 4'd0;

endmodule
