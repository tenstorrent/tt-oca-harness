// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Primitive Programmable Clock Divider
//
//--------------------------------------------------
module prim_prog_clk_div_posedge #(
  parameter int unsigned RESET_WIDTH = 16,  // Reset width in clock cycles
  parameter bit [7:0] INITIAL_DIVIDER_VAL = 8'd2,
  parameter bit DIVIDED_CLOCK_ON_RESET = 1'b0
) (
  input logic clk_i,
  input logic rst_ni,
  input logic update_settings_i,
  input logic [7:0] divider_i,
  input logic [7:0] duty_cycle_i,
  input logic use_clk_div_i,
  input logic test_en_i,
  input logic scan_rst_ni,

  output logic clk_o
);

  logic div_clk;
  logic div_clk_buf;
  logic reset_n_syncd;
  logic [7:0] divider;
  logic [7:0] capped_divider;
  logic [7:0] duty_cycle_numerator;
  logic [7:0] capped_duty_cycle_numerator;
  logic [15:0] divider_times_duty_numerator;
  logic [7:0] count;
  logic [7:0] div_clk_high_periods;
  logic [7:0] uncapped_div_clk_high_periods;
  logic [7:0] div_clk_low_periods;
  logic [8:0] div_clk_low_periods_underflow;

  prim_sync_reset #(
    .WIDTH(RESET_WIDTH)
  ) reset_sync (
    .clk(clk_i),
    .rst_n(rst_ni),
    .test_mode(test_en_i),
    .scan_rst_n(scan_rst_ni),
    .sync_rst_n(reset_n_syncd)
  );

  always_ff @(posedge clk_i) begin
    if (~reset_n_syncd) begin
      divider <= INITIAL_DIVIDER_VAL;
      duty_cycle_numerator <= 8'b10000000;
    end else if (update_settings_i) begin
      divider <= divider_i;
      duty_cycle_numerator <= duty_cycle_i;
    end
  end

  assign capped_divider = divider < 8'd2 ? 8'd2 : divider;
  assign capped_duty_cycle_numerator = duty_cycle_numerator == 0 ? 8'd1 : duty_cycle_numerator;

  assign divider_times_duty_numerator = capped_divider * capped_duty_cycle_numerator;
  assign uncapped_div_clk_high_periods = 8'(divider_times_duty_numerator >> 8);
  assign div_clk_high_periods = uncapped_div_clk_high_periods == 0 ? 8'd1 : uncapped_div_clk_high_periods == capped_divider ? capped_divider - 1 : uncapped_div_clk_high_periods ;
  assign div_clk_low_periods_underflow = capped_divider - div_clk_high_periods;
  assign div_clk_low_periods = div_clk_low_periods_underflow[7:0];

  always_ff @(posedge clk_i) begin
    if (~reset_n_syncd) begin
      count <= div_clk_low_periods - 1;
    end else if (count == 0) begin
      count <= (div_clk_buf ? div_clk_low_periods : div_clk_high_periods) - 1;
    end else begin
      count <= count - 1'b1;
    end
  end

  always_ff @(posedge clk_i) begin
    if (~reset_n_syncd) begin
      div_clk <= 1'b0;
    end else if (count == 0) begin
      div_clk <= ~div_clk_buf;
    end
  end

  prim_stdbuf div_clk_stdbuf (
    .i_A(div_clk),
    .o_Y(div_clk_buf)
  );

  //here, unbuffered div_clk continues into glitch-free mux.
  // clk_i and div_clk are in the same clock domain (div_clk is derived from
  // clk_i), so a single reset_n_syncd is correct for both rst0_ni and rst1_ni.
  prim_ag_clk_mux #(
    .SelectOnReset(DIVIDED_CLOCK_ON_RESET)
  ) postdiv_mux (
    .clk0_i(clk_i),
    .clk1_i(div_clk),
    .rst_clk0_ni(reset_n_syncd),
    .rst_clk1_ni(reset_n_syncd),
    .test_en_i(1'b0),
    .sel_i(use_clk_div_i),
    .clk_o(clk_o)
  );

endmodule
