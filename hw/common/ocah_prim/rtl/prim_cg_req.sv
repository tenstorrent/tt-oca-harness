// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Drive Q-Channel qreq_no from qactive_i, qaccept_ni, and qdeny_i.
//
// qreq_no is the active-low quiescence request: it follows qactive_i, so it falls, asking
// for the clock to stop, once the device is idle.
// After a deny, hold qreq_no high (request withdrawn) for DENY_DELAY cycles before it
// follows qactive_i again; an accept clears the hold.
// HysteresisW sizes the deny-hold counter.

module prim_cg_req #(
  parameter int unsigned DENY_DELAY = 1,  // Cycles to hold after a deny before reasserting.

  localparam int unsigned HysteresisW = (DENY_DELAY <= 1) ? 1 : $clog2(DENY_DELAY+1)  // Deny-hold counter width.
) (
  input  logic clk_i,  // Q-Channel clock.
  input  logic rst_ni,  // Async reset, active-low.

  input  logic qactive_i,  // Device wants the clock.
  input  logic qaccept_ni,  // Device accepted the quiescence request, active-low.
  input  logic qdeny_i,  // Device denied the quiescence request; starts the deny hold.
  output logic qreq_no  // Quiescence request to the device, active-low; low asks for
                        // the clock to stop.
);

  `include "prim_assert.sv"

  ////////////////////////////////////////////////////////////////////////////////
  // Local Parameters and Types
  ////////////////////////////////////////////////////////////////////////////////

  typedef logic [HysteresisW-1:0] count_t;

  ////////////////////////////////////////////////////////////////////////////////
  // Signal Declarations
  ////////////////////////////////////////////////////////////////////////////////

  // Delay counter for deny hysteresis
  count_t count_q, count_d;

  ////////////////////////////////////////////////////////////////////////////////
  // Sequential Logic
  ////////////////////////////////////////////////////////////////////////////////

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      count_q <= count_t'(0);
    end else begin
      count_q <= count_d;
    end
  end

  ////////////////////////////////////////////////////////////////////////////////
  // Combinational Logic
  ////////////////////////////////////////////////////////////////////////////////

  // Clock gating request logic with deny delay hysteresis
  always_comb begin
    count_d = count_q;

    // Request accepted - reset counter
    if (!qreq_no && !qaccept_ni) begin
      count_d = count_t'(0);
    end  // Request denied - start delay counter
    else if (!qreq_no && qdeny_i) begin
      count_d = count_t'(DENY_DELAY);
    end  // Counting down delay
    else if (|count_q) begin
      count_d = count_q - count_t'(1);
    end
  end

  ////////////////////////////////////////////////////////////////////////////////
  // Output Assignments
  ////////////////////////////////////////////////////////////////////////////////

  assign qreq_no = ~|count_q ? qactive_i : 1'b1;

  ////////////////////////////////////////////////////////////////////////////////
  // Assertions
  ////////////////////////////////////////////////////////////////////////////////

  // Validate parameters
  `OCAH_OT_ASSERT_INIT(ValidDenyDelay_A, DENY_DELAY >= 1)

  // Validate input signals
  `OCAH_OT_ASSERT_KNOWN(QActiveKnown_A, qactive_i, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(QAcceptKnown_A, qaccept_ni, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(QDenyKnown_A, qdeny_i, clk_i, !rst_ni)

  // Counter should not exceed DENY_DELAY
  `OCAH_OT_ASSERT(CounterBounds_A, count_q <= count_t'(DENY_DELAY), clk_i, !rst_ni)

endmodule
