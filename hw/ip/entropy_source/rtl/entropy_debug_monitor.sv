// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_debug_monitor.sv
 * @brief Debug monitor for entropy source signals.
 *
 * @details Selects a single bit from NSIGNALS inputs and optionally divides
 *          it down in frequency by a power-of-two factor before routing it
 *          off-chip as a debug observable. The frequency divider provides
 *          factors 2^0 through 2^(FREQ_DIV_WIDTH-1).
 *
 * @param NSIGNALS       Number of input signals to select from (default: 32)
 * @param FREQ_DIV_WIDTH Number of frequency division stages (default: 8)
 */

module entropy_debug_monitor #(
  parameter int unsigned NSIGNALS       = 32,
  parameter int unsigned FREQ_DIV_WIDTH = 8
) (
  input       logic                                rst_ni,
  input       logic [$clog2(NSIGNALS)-1:0]         select_signal_i,
  input       logic [NSIGNALS-1:0]                 signal_i,
  input       logic [$clog2(FREQ_DIV_WIDTH-1)-1:0] select_freq_div_i,
  output      logic                                sig_monitor_o
);

  /////////////
  // Signals
  /////////////

  logic [NSIGNALS-1:0]       select_signal_binary_decode;
  logic [NSIGNALS-1:0]       select_signal;
  logic                      fast_signal;
  logic [FREQ_DIV_WIDTH-1:0] div_signals;
  logic [FREQ_DIV_WIDTH-1:0] select_freq_binary_decode;

  /////////////////
  // Combinational
  /////////////////

  always_comb begin
    for (int i = 0; i < NSIGNALS; i++) begin
      select_signal_binary_decode[i] = select_signal_i == i[$clog2(NSIGNALS)-1:0];
    end
  end

  assign select_signal = select_signal_binary_decode & signal_i;
  assign fast_signal   = |select_signal;

  always_comb begin
    for (int i = 0; i < FREQ_DIV_WIDTH; i++) begin
      select_freq_binary_decode[i] = select_freq_div_i == i[$clog2(FREQ_DIV_WIDTH-1)-1:0];
    end
  end

  /////////////////
  // Sub-instances
  /////////////////

  entropy_ripple_divider #(
    .NUM_STAGES(FREQ_DIV_WIDTH - 1)
  ) u_ripple_divider (
    .rst_ni (rst_ni),
    .clk_i  (fast_signal),
    .div_o  (div_signals)
  );

  ///////////
  // Output
  ///////////

  assign sig_monitor_o = |(select_freq_binary_decode & div_signals);

endmodule
