// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Reset sequencing FSM for one software-resettable domain. On a software
// reset request, requests isolation of the domain's AXI paths, waits until
// all of them report isolated, then asserts the domain reset. Isolation is
// held until the software reset request is released.

`include "ocah_assert.svh"

module sep_isolate_rst_seq (
  input  logic clk_i,
  input  logic rst_ni,
  // Software reset request (active low)
  input  logic sw_rst_req_ni,
  // All of the domain's isolate units report isolated
  input  logic isolated_i,
  // Isolation request to the domain's isolate units
  output logic isolate_req_o,
  // Sequenced reset to the domain (active low)
  output logic gated_rst_no
);

  typedef enum logic [1:0] {
    StReset,  // domain in reset, paths isolated
    StDrain,  // isolation requested, waiting for in-flight drain
    StRun  // normal operation
  } isolate_state_e;

  isolate_state_e state_q, state_d;
  logic gated_rst_d, gated_rst_n_q;

  always_comb begin
    state_d = state_q;

    unique case (state_q)
      StRun: begin
        if (~sw_rst_req_ni) begin
          state_d = StDrain;
        end
      end
      StDrain: begin
        if (isolated_i) begin
          state_d = StReset;
        end
      end
      StReset: begin
        if (sw_rst_req_ni) begin
          state_d = StRun;
        end
      end
      default: state_d = StReset;
    endcase
  end

  assign isolate_req_o = (state_q != StRun);  // Isolation requested when not in normal operation
  assign gated_rst_d   = (state_d == StReset);  // Domain reset asserted when in reset state

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      state_q <= StReset;
    end else begin
      state_q <= state_d;
    end
  end

  // Flopped so the domain reset only makes clean, clock-aligned transitions.
  // Reset value 0 = domain reset asserted while rst_ni is asserted.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      gated_rst_n_q <= 1'b0;
    end else begin
      gated_rst_n_q <= ~gated_rst_d;
    end
  end

  assign gated_rst_no = gated_rst_n_q;

  // The domain reset must never assert while a path is still open.
  `OCAH_ASSERT(ResetOnlyWhenIsolated_A, !gated_rst_no |-> isolated_i, clk_i, !rst_ni)

  // Isolation must be held for the entire duration of the domain reset.
  `OCAH_ASSERT(IsolateHeldThroughReset_A, !gated_rst_no |-> isolate_req_o, clk_i, !rst_ni)

endmodule
