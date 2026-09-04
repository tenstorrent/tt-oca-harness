// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AXI Bus Snooping Module
//
//--------------------------------------------------

module prim_axi_snoop #(
  parameter int unsigned OutstandingTx = 1,

  // Derived parameters
  localparam int unsigned OutstandingTxW = OutstandingTx > 1 ? $clog2(OutstandingTx) + 1 : 1
) (
  input  logic        clk_i,
  input  logic        rst_ni,

  // AXI Write Address Channel Snoop
  input  logic        snoop_aw_valid_i,
  input  logic        snoop_aw_ready_i,

  // AXI Write Data Channel Snoop
  input  logic        snoop_w_valid_i,

  // AXI Write Response Channel Snoop
  input  logic        snoop_b_valid_i,
  input  logic        snoop_b_ready_i,

  // AXI Read Address Channel Snoop
  input  logic        snoop_ar_valid_i,
  input  logic        snoop_ar_ready_i,

  // AXI Read Data Channel Snoop
  input  logic        snoop_r_valid_i,
  input  logic        snoop_r_ready_i,
  input  logic        snoop_r_last_i,

  // Activity Indicator
  output logic                    bus_active_o,

  // Probes for downstream hang detection (axi_hang_detector consumes these)
  output logic                    complete_aw_o,
  output logic                    complete_ar_o,
  output logic [OutstandingTxW:0] req_count_q_o
);

  `include "prim_assert.sv"

  ////////////////////////////////////////////////////////////////////////////////
  // Local Parameters and Types
  ////////////////////////////////////////////////////////////////////////////////

  typedef logic [OutstandingTxW:0] count_t;
  localparam int unsigned CountCalcW = OutstandingTxW + 3; // extra bits for accept+complete arithmetic

  ////////////////////////////////////////////////////////////////////////////////
  // Signal Declarations
  ////////////////////////////////////////////////////////////////////////////////

  // Request counting signals
  count_t req_count_q, req_count_d;

  // Transaction tracking
  logic accept_aw, accept_ar;
  logic complete_aw, complete_ar;

  logic aw_valid_q, aw_handshake_q;
  logic ar_valid_q, ar_handshake_q;


  ////////////////////////////////////////////////////////////////////////////////
  // Transaction Tracking Logic
  ////////////////////////////////////////////////////////////////////////////////

  // Detect transaction acceptance and completion
  always_comb begin

    // Accept transactions on rising edge or one cycle after handshake while valid still asserted
    // (aw_valid && !aw_valid_q detects rising edge)
    accept_aw   = (snoop_aw_valid_i && !aw_valid_q) || (snoop_aw_valid_i && aw_handshake_q);
    accept_ar   = (snoop_ar_valid_i && !ar_valid_q) || (snoop_ar_valid_i && ar_handshake_q);

    // Complete transactions on b/r handshakes
    complete_aw = snoop_b_valid_i && snoop_b_ready_i;
    complete_ar = snoop_r_valid_i && snoop_r_ready_i && snoop_r_last_i;

    req_count_d = count_t'(CountCalcW'(req_count_q) + CountCalcW'(accept_aw) + CountCalcW'(accept_ar) -
                     CountCalcW'(complete_aw) - CountCalcW'(complete_ar));
  end

  // Activity detection - active when there are pending requests or write data
  assign bus_active_o = |{snoop_aw_valid_i, snoop_w_valid_i, snoop_ar_valid_i, req_count_q};

  // Expose internal probes for downstream hang detection
  assign complete_aw_o = complete_aw;
  assign complete_ar_o = complete_ar;
  assign req_count_q_o = req_count_q;

  ////////////////////////////////////////////////////////////////////////////////
  // Sequential Logic - Request Counter
  ////////////////////////////////////////////////////////////////////////////////

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      req_count_q <= count_t'(0);

      aw_valid_q     <= 1'b0;
      aw_handshake_q <= 1'b0;
      ar_valid_q     <= 1'b0;
      ar_handshake_q <= 1'b0;

    end else begin
      req_count_q <= req_count_d;

      aw_valid_q     <= snoop_aw_valid_i;
      aw_handshake_q <= snoop_aw_valid_i && snoop_aw_ready_i;
      ar_valid_q     <= snoop_ar_valid_i;
      ar_handshake_q <= snoop_ar_valid_i && snoop_ar_ready_i;

    end
  end

  ////////////////////////////////////////////////////////////////////////////////
  // Assertions
  ////////////////////////////////////////////////////////////////////////////////

  // Parameter Validation
  `OCAH_OT_ASSERT_INIT(ValidOutstandingTx_A, OutstandingTx >= 1)

  // Check for request counter underflow
  `OCAH_OT_ASSERT_NEVER(ReqCountUnderflow_A, ~|req_count_q && ($countones
                        ({complete_ar, complete_aw}) > $countones({accept_ar, accept_aw})))

  // Check for request counter overflow
  `OCAH_OT_ASSERT_NEVER(ReqCountOverflow_A, &req_count_q && ($countones({complete_ar, complete_aw})
                        < $countones({accept_ar, accept_aw})))

endmodule
