// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Toggle ring-oscillator detune once per new health-test failure edge.
//
// A rising edge on health_error_i (0→1) flips tune_state_o to an alternate detune
// setting.
// While the error stays asserted the state does not re-toggle; when the error clears the
// current detune setting is preserved.

module entropy_rosc_tune_fsm (
  input       logic clk_i,              // System clock.
  input       logic rst_ni,             // Active-low reset.
  input       logic health_error_i,     // Health error.
  output      logic tune_state_o        // Tune state.
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
