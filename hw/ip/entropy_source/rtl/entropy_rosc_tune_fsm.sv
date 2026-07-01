// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Noise Source
//
// Description:
// The individual entropy noise source ring oscillators can be automatically
// detuned when the auto detuning is enabled and the enabled health tests
// indicate statistical failures.
//
// This FSM toggles the tune state only on rising edges (0->1) of health_error_i,
// representing new health error events. When a health error is detected, the FSM
// switches to an alternate detune setting. When the error clears (1->0), the
// current detune setting is maintained since it successfully resolved the issue.
// Edge detection ensures the state only changes once per new error, not
// continuously whilst the error signal remains asserted.
//
// Behavior:
//   - Rising edge (0->1): New health error detected -> Toggle detune state
//   - Falling edge (1->0): Health error cleared -> Keep current detune state
//   - Held HIGH/LOW: Detune state remains stable (no toggling)
//------------------------------------------------------------------------------

module entropy_rosc_tune_fsm (
    input  logic clk_i,
    input  logic rst_ni,
    input  logic health_error_i,
    output logic tune_state_o
);

    typedef enum logic [0:0] {
        STATE_0,
        STATE_1
    } state_e;

    state_e state, next_state;

    logic health_error_d;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            health_error_d <= 1'b0;
        end else begin
            health_error_d <= health_error_i;
        end
    end

    logic health_error_rising;

    assign health_error_rising  = health_error_i & ~health_error_d;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            state <= STATE_0;
        end else begin
            state <= next_state;
        end
    end

    always_comb begin
        next_state = state;

        case (state)
            STATE_0: begin
                if (health_error_rising) begin  // Transition only on rising edge (new error)
                    next_state = STATE_1;
                end
            end
            STATE_1: begin
                if (health_error_rising) begin  // Transition only on rising edge (new error)
                    next_state = STATE_0;
                end
            end
            default: begin
                next_state = state;
            end
        endcase
    end

    assign tune_state_o = state;
endmodule
