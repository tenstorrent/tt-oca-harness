// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Toggle ring-oscillator detune once per new health-test failure edge.
//
// A rising edge on health_error_i (0→1) flips tune_state_o to an alternate detune
// setting.
// While the error stays asserted the state does not re-toggle; when the error clears the
// current detune setting is preserved.

`include "ocah_registers.svh"

module entropy_rosc_tune_fsm (
  input       logic clk_i,              // System clock.
  input       logic rst_ni,             // Active-low reset.
  input       logic health_error_i,     // Any health-test failure; each rising edge toggles
                                        // tune_state_o.
  output      logic tune_state_o        // Detune selection for the ring oscillator; low after
                                        // reset.
);

  /////////////
  // Types
  /////////////

  typedef enum logic [0:0] {
    STATE_0,
    STATE_1
  } state_e;

  /////////////
  // Signals
  /////////////

  state_e state_q, state_d;

  logic health_error_d;
  logic health_error_rising;

  ///////////////
  // Sequential
  ///////////////

  `OCAH_FF(health_error_d, health_error_i, 1'b0, clk_i, rst_ni)

  `OCAH_FF(state_q, state_d, STATE_0, clk_i, rst_ni)

  /////////////////
  // Combinational
  /////////////////

  assign health_error_rising = health_error_i & ~health_error_d;

  always_comb begin
    state_d = state_q;

    unique case (state_q)
      STATE_0: begin
        if (health_error_rising) begin
          state_d = STATE_1;
        end
      end
      STATE_1: begin
        if (health_error_rising) begin
          state_d = STATE_0;
        end
      end
      default: begin
        state_d = state_q;
      end
    endcase
  end

  ///////////
  // Output
  ///////////

  assign tune_state_o = state_q;

endmodule
