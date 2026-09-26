// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Stretch a core-side pulse to stretch_mult_i+1 clk_i cycles for wire-OR mode.
//
// pulse_i is synchronous to clk_i; a new pulse while stretching restarts the counter so
// every chiplet still sees the event.
// stretched_pulse_o is the registered stretched pulse.

module ctp_pulse_stretcher (
  input  logic        clk_i,            // System clock.
  input  logic        rst_ni,           // Active-low reset.

  input  logic        pulse_i,          // Pulse.

  input  logic [15:0] stretch_mult_i,   // Stretch mult.

  output logic        stretched_pulse_o  // Stretched pulse.
);

  logic [15:0] counter_q, counter_d;
  logic active_q, active_d;

  // Counter logic: count down from stretch_mult_i to 0
  always_comb begin
    counter_d = counter_q;
    active_d  = active_q;

    if (pulse_i) begin
      // New pulse arrives - restart counter
      counter_d = stretch_mult_i;
      active_d  = 1'b1;
    end else if (active_q && (counter_q != 16'd0)) begin
      // Count down while active
      counter_d = counter_q - 16'd1;
      active_d  = 1'b1;
    end else begin
      // Counter reached zero or not active
      counter_d = 16'd0;
      active_d  = 1'b0;
    end
  end

  // Registered outputs
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      counter_q <= 16'd0;
      active_q  <= 1'b0;
    end else begin
      counter_q <= counter_d;
      active_q  <= active_d;
    end
  end

  // Output is active when counter is non-zero or just started
  assign stretched_pulse_o = active_q;

endmodule : ctp_pulse_stretcher
