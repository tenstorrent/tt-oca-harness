// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Pulse Stretcher Module
//
// Description:
// Stretches a core-side pulse to (STRETCH_MULT + 1) clock cycles for wire-OR mode.
// If a new pulse arrives before the current pulse finishes stretching, the counter
// is restarted to ensure all chiplets see the pulse.
//------------------------------------------------------------------------------


module ctp_pulse_stretcher (
  input  logic        clk_i,
  input  logic        rst_ni,

  // Pulse input (synchronous to clk_i)
  input  logic        pulse_i,

  // Stretch multiplier (number of cycles to stretch)
  input  logic [15:0] stretch_mult_i,

  // Stretched pulse output (registered)
  output logic        stretched_pulse_o
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
