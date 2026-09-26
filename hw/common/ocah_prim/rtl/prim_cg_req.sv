// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Clock Gating Request
//
//--------------------------------------------------

module prim_cg_req #(
  parameter int unsigned DenyDelay = 1,

  // Derived parameters
  localparam int unsigned HysteresisW = (DenyDelay <= 1) ? 1 : $clog2(DenyDelay)
) (
  input  logic clk_i,
  input  logic rst_ni,

  // Power management interface
  input  logic qactive_i,
  input  logic qaccept_ni,
  input  logic qdeny_i,
  output logic qreq_no
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
      count_d = count_t'(DenyDelay);
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
  `OCAH_OT_ASSERT_INIT(ValidDenyDelay_A, DenyDelay >= 1)

  // Validate input signals
  `OCAH_OT_ASSERT_KNOWN(QActiveKnown_A, qactive_i, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(QAcceptKnown_A, qaccept_ni, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(QDenyKnown_A, qdeny_i, clk_i, !rst_ni)

  // Counter should not exceed DenyDelay
  `OCAH_OT_ASSERT(CounterBounds_A, count_q <= count_t'(DenyDelay), clk_i, !rst_ni)

endmodule
