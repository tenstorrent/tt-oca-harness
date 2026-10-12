// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Stretch a core-side pulse to stretch_mult_i+1 clk_i cycles for wire-OR mode.
//
// pulse_i is synchronous to clk_i; a new pulse while stretching restarts the counter so
// every chiplet still sees the event.
// stretched_pulse_o is the registered stretched pulse.

`include "ocah_registers.svh"

module ctp_pulse_stretcher (
  input  logic        clk_i,            // System clock.
  input  logic        rst_ni,           // Active-low asynchronous reset; clears the counter and the
                                        // output.

  input  logic        pulse_i,          // Outgoing core-side cross-trigger pulse, synchronous to
                                        // clk_i; each assertion reloads the stretch counter.

  input  logic [15:0] stretch_mult_i,   // Stretch length: the output stays high for
                                        // stretch_mult_i+1 clk_i cycles after the most recent
                                        // pulse_i.

  output logic        stretched_pulse_o  // Stretched pulse, registered and reset low; drives the
                                         // CT_Req_out output enable in wire-OR mode.
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
  `OCAH_FF(counter_q, counter_d, 16'd0, clk_i, rst_ni)
  `OCAH_FF(active_q, active_d, 1'b0, clk_i, rst_ni)

  // Output is active when counter is non-zero or just started
  assign stretched_pulse_o = active_q;

endmodule : ctp_pulse_stretcher
