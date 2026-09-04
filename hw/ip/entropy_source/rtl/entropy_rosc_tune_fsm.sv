// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_rosc_tune_fsm.sv
 * @brief Ring-oscillator auto-tune FSM for health-test driven detuning.
 *
 * @details Toggles the tune-state of an RO lane on rising edges of
 *          health_error_i. A rising edge (0->1) represents a new health-test
 *          failure and drives the FSM to an alternate detune setting. Once the
 *          error clears the current detune state is preserved (it resolved the
 *          issue). Edge detection ensures the state toggles exactly once per
 *          new error event, not continuously while the error signal remains
 *          asserted.
 */

module entropy_rosc_tune_fsm (
  input       logic clk_i,
  input       logic rst_ni,
  input       logic health_error_i,
  output      logic tune_state_o
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

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      health_error_d <= 1'b0;
    end else begin
      health_error_d <= health_error_i;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= STATE_0;
    end else begin
      state_q <= state_d;
    end
  end

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
