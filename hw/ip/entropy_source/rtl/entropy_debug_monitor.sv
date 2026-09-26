// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Select one of NSIGNALS inputs and optionally divide it for an off-chip debug observe pin.
//
// select_signal_i chooses the bit; select_freq_div_i selects a power-of-two divider from
// 2^0 through 2^(FREQ_DIV_WIDTH-1).
// sig_monitor_o is the divided observable.

module entropy_debug_monitor #(
  parameter int unsigned NSIGNALS       = 32,  // Selectable monitor input count.
  parameter int unsigned FREQ_DIV_WIDTH = 8  // Divider tap count including the undivided signal;
                                             // the ripple divider has FREQ_DIV_WIDTH-1 stages.
) (
  input       logic                                rst_ni,  // Active-low asynchronous reset of the
                                                            // ripple divider.
  input       logic [$clog2(NSIGNALS)-1:0]         select_signal_i,  // Binary index of the signal_i bit to observe.
  input       logic [NSIGNALS-1:0]                 signal_i,  // Candidate observe signals; bit
                                                              // select_signal_i clocks the ripple
                                                              // divider.
  input       logic [$clog2(FREQ_DIV_WIDTH-1)-1:0] select_freq_div_i,  // Divider tap index; value k observes the selected
                                                                       // signal divided by 2^k.
  output      logic                                sig_monitor_o  // Selected signal after the
                                                                  // chosen power-of-two divider,
                                                                  // for an off-chip observe pin.
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
