// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Snoop AXI handshakes and report bus activity plus outstanding counts.
//
// Count a request when AW or AR valid rises, or stays high in the cycle after a handshake,
// and retire it on the B handshake or the R handshake carrying last.
// Drive bus_active_o high while AW, W or AR valid is asserted or any counted request is open.
// Pulse complete_aw_o on each B handshake and complete_ar_o on each last-beat R handshake.
// Export req_count_q_o for downstream hang detectors such as axi_hang_detector.

`include "ocah_registers.svh"

module prim_axi_snoop #(
  parameter int unsigned OUTSTANDING_TX = 1,  // Max outstanding transactions tracked; sizes the
                                              // counter.

  localparam int unsigned OutstandingTxW = OUTSTANDING_TX > 1 ? $clog2(OUTSTANDING_TX) + 1 : 1  // Derived from OUTSTANDING_TX; the counter is one bit wider.
) (
  input  logic        clk_i,  // AXI clock.
  input  logic        rst_ni,  // Async reset, active-low.

  input  logic        snoop_aw_valid_i,  // Snooped AW valid.
  input  logic        snoop_aw_ready_i,  // Snooped AW ready.

  input  logic        snoop_w_valid_i,  // Snooped W valid; only keeps bus_active_o high.

  input  logic        snoop_b_valid_i,  // Snooped B valid.
  input  logic        snoop_b_ready_i,  // Snooped B ready.

  input  logic        snoop_ar_valid_i,  // Snooped AR valid.
  input  logic        snoop_ar_ready_i,  // Snooped AR ready.

  input  logic        snoop_r_valid_i,  // Snooped R valid.
  input  logic        snoop_r_ready_i,  // Snooped R ready.
  input  logic        snoop_r_last_i,  // Snooped R last.

  output logic                    bus_active_o,  // High while AW, W or AR valid is high or the
                                                 // count is nonzero.

  output logic                    complete_aw_o,  // Combinational pulse on each B handshake.
  output logic                    complete_ar_o,  // Combinational pulse on each R handshake with
                                                  // last set.
  output logic [OutstandingTxW:0] req_count_q_o  // Registered count of open write and read
                                                 // requests.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

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

  `OCAH_FF(req_count_q, req_count_d, count_t'(0), clk_i, rst_ni)
  `OCAH_FF(aw_valid_q, snoop_aw_valid_i, 1'b0, clk_i, rst_ni)
  `OCAH_FF(aw_handshake_q, snoop_aw_valid_i && snoop_aw_ready_i, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ar_valid_q, snoop_ar_valid_i, 1'b0, clk_i, rst_ni)
  `OCAH_FF(ar_handshake_q, snoop_ar_valid_i && snoop_ar_ready_i, 1'b0, clk_i, rst_ni)

  ////////////////////////////////////////////////////////////////////////////////
  // Assertions
  ////////////////////////////////////////////////////////////////////////////////

  // Parameter Validation
  `OCAH_ASSERT_STATIC(ValidOutstandingTx_A, OUTSTANDING_TX >= 1)

  // Check for request counter underflow
  `OCAH_OT_ASSERT_NEVER(ReqCountUnderflow_A, ~|req_count_q && ($countones
                        ({complete_ar, complete_aw}) > $countones({accept_ar, accept_aw})))

  // Check for request counter overflow
  `OCAH_OT_ASSERT_NEVER(ReqCountOverflow_A, &req_count_q && ($countones({complete_ar, complete_aw})
                        < $countones({accept_ar, accept_aw})))

endmodule
