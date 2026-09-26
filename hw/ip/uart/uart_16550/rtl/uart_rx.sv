// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Sample rx_i at 16× baud and assemble a UART receive frame.
//
// tick_baud_x16_i paces oversampling; word_length_i, parity_enable_i, parity_odd_i, and
// extra_stop_bit_i shape the expected frame.
// rx_valid_o pulses with rx_data_o; frame_err_o and rx_parity_err_o report framing and
// parity faults.

module uart_rx
  import uart_16550_pkg::*;
#(
) (
  input  logic       clk_i,             // System clock.
  input  logic       rst_ni,            // Active-low reset.

  input  logic       rx_enable_i,       // Receiver enable.
  input  logic       tick_baud_x16_i,   // 16× baud oversample tick.
  input  logic       parity_enable_i,   // Include a parity bit in the frame.
  input  logic       parity_odd_i,      // 1 selects odd parity; 0 selects even.
  input  logic       parity_force_i,    // Force parity value for testing.
  input  logic [3:0] word_length_i,     // Data bits per frame.
  input  logic       extra_stop_bit_i,  // Add a second stop bit when high.

  output logic       tick_baud_o,       // Tick baud.
  output logic       rx_valid_o,        // Pulse when rx_data_o is valid.
  output logic [7:0] rx_data_o,         // Received data byte.
  output logic       idle_o,            // High when the shifter is empty or tx_enable_i is low.
  output logic       frame_err_o,       // Framing error.
  output logic       rx_parity_err_o,   // Parity error.

  input logic        rx_i               // Serial receive line.
);

  logic [11:0] sreg_q, sreg_d;
  logic [3:0] bit_cnt_q, bit_cnt_d;
  logic [3:0] baud_div_q, baud_div_d;
  logic tick_baud_d, tick_baud_q;
  logic idle_d, idle_q;

  assign tick_baud_o = tick_baud_q;
  assign idle_o      = idle_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      sreg_q      <= 12'h0;
      bit_cnt_q   <= 4'd0;
      baud_div_q  <= 4'd0;
      tick_baud_q <= 1'b0;
      idle_q      <= 1'b1;
    end else begin
      sreg_q      <= sreg_d;
      bit_cnt_q   <= bit_cnt_d;
      baud_div_q  <= baud_div_d;
      tick_baud_q <= tick_baud_d;
      idle_q      <= idle_d;
    end
  end

  logic [3:0] frame_length;

  assign frame_length = get_frame_length(RX, word_length_i, extra_stop_bit_i, parity_enable_i);

  always_comb begin
    if (!rx_enable_i) begin
      sreg_d      = 12'h0;
      bit_cnt_d   = 4'd0;
      baud_div_d  = 4'd0;
      tick_baud_d = 1'b0;
      idle_d      = 1'b1;
    end else begin
      tick_baud_d = 1'b0;
      sreg_d      = sreg_q;
      bit_cnt_d   = bit_cnt_q;
      baud_div_d  = baud_div_q;
      idle_d      = idle_q;
      if (tick_baud_x16_i) begin
        {tick_baud_d, baud_div_d} = {1'b0, baud_div_q} + 5'd1;
      end

      if (idle_q && rx_i == 1'b0) begin
        // start of char, sample in the middle of the bit time
        baud_div_d  = 4'd8;
        tick_baud_d = 1'b0;
        bit_cnt_d   = frame_length;
        sreg_d      = 12'h0;
        idle_d      = 1'b0;
      end else if (!idle_q && tick_baud_q) begin
        if (bit_cnt_q == frame_length && rx_i != 1'b0) begin
          // must have been a glitch on the input, start bit is not set
          // in the middle of the bit time, abort
          idle_d    = 1'b1;
          bit_cnt_d = 4'd0;
        end else begin
          sreg_d    = {rx_i, sreg_q[11:1]};
          bit_cnt_d = bit_cnt_q  - 4'd1;
          idle_d    = bit_cnt_q == 4'd1;
        end
      end
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) rx_valid_o <= 1'b0;
    else rx_valid_o <= tick_baud_q && bit_cnt_q == 4'd1;
  end

  assign rx_data_o = get_rx_data_from_frame(
                           sreg_q,
                           word_length_i,
                           extra_stop_bit_i,
                           parity_enable_i
                       );

  assign frame_err_o = rx_valid_o && (
                             extra_stop_bit_i && word_length_i != 4'd5 ? sreg_q[11:10] != 2'h3 :
                                                                         sreg_q[11]    != 1'h1
                         );
  logic rx_parity;
  assign rx_parity = (extra_stop_bit_i && word_length_i != 4'd5) ? sreg_q[9] : sreg_q[10];
  // When forced parity is enabled, we force the parity bit to be 1 if odd parity is enabled
  // and 0 if even parity is enabled. This effectively means that we check if
  // there is an even number of 1's in the data bits.
  assign rx_parity_err_o = parity_enable_i && rx_valid_o && (
                                 parity_force_i ?  ^rx_data_o :
                                 parity_odd_i   ? ~^{rx_parity, rx_data_o} :
                                                   ^{rx_parity, rx_data_o}
                             );

endmodule
