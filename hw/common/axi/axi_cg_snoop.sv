// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AXI Clock Gating Snoop Module with Hysteresis
//
// This module integrates three components for comprehensive AXI-aware power management:
//
// 1. AXI Bus Snooping: Tracks outstanding AXI transactions and detects activity
// 2. Clock Gating Request: Manages power requests with deny delay functionality
// 3. Clock Gater with Hysteresis: Provides actual clock gating with configurable delay
//
// The complete flow is:
// AXI Activity → Bus Snoop → Activity Detection → CG Request → Clock Gater → Gated Clock
//
// Key features:
// - Monitors all AXI channels (AW, W, B, AR, R) for transaction activity
// - Implements deny delay hysteresis to prevent excessive power state transitions
// - Provides configurable clock gating delay for smooth power transitions
// - Generates both power management requests and actual gated clocks


module axi_cg_snoop #(
  parameter int unsigned OUTSTANDING_TX = 1,
  parameter int unsigned DENY_DELAY = 1,
  parameter int unsigned HYST_WIDTH = 6
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,

  // AXI Write Address Channel Snoop
  input  logic                    snoop_aw_valid_i,
  input  logic                    snoop_aw_ready_i,

  // AXI Write Data Channel Snoop
  input  logic                    snoop_w_valid_i,

  // AXI Write Response Channel Snoop
  input  logic                    snoop_b_valid_i,
  input  logic                    snoop_b_ready_i,

  // AXI Read Address Channel Snoop
  input  logic                    snoop_ar_valid_i,
  input  logic                    snoop_ar_ready_i,

  // AXI Read Data Channel Snoop
  input  logic                    snoop_r_valid_i,
  input  logic                    snoop_r_ready_i,
  input  logic                    snoop_r_last_i,

  // Clock Gating Interface
  input  logic                    kick_i,
  input  logic                    test_clk_en_i,
  input  logic [HYST_WIDTH-1:0]   hysteresis_i,
  output logic                    clk_active_o,
  output logic                    gated_clk_o,

  // Activity Indicator Output
  output logic                    bus_active_o
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  ////////////////////////////////////////////////////////////////////////////////
  // Parameter Validation
  ////////////////////////////////////////////////////////////////////////////////

  `OCAH_ASSERT_STATIC(ValidOutstandingTx_A, OUTSTANDING_TX >= 1)
  `OCAH_ASSERT_STATIC(ValidDenyDelay_A, DENY_DELAY >= 1)
  `OCAH_ASSERT_STATIC(ValidHystWidth_A, HYST_WIDTH >= 1 && HYST_WIDTH <= 32)

  ////////////////////////////////////////////////////////////////////////////////
  // Internal Signals
  ////////////////////////////////////////////////////////////////////////////////

  // Internal activity signal connecting AXI snoop to CG request
  logic bus_active_internal;

  // Clock gating enable signal (active high, derived from qreq_n which is active low)
  logic cg_enable_internal;

  // Request to gate from AXI snoop
  logic qreq_n;

  ////////////////////////////////////////////////////////////////////////////////
  // AXI Bus Snooping Instance
  ////////////////////////////////////////////////////////////////////////////////

  prim_axi_snoop #(
    .OUTSTANDING_TX(OUTSTANDING_TX)
  ) u_axi_snoop (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),

    // AXI Write Address Channel Snoop
    .snoop_aw_valid_i    (snoop_aw_valid_i),
    .snoop_aw_ready_i    (snoop_aw_ready_i),

    // AXI Write Data Channel Snoop
    .snoop_w_valid_i     (snoop_w_valid_i),

    // AXI Write Response Channel Snoop
    .snoop_b_valid_i     (snoop_b_valid_i),
    .snoop_b_ready_i     (snoop_b_ready_i),

    // AXI Read Address Channel Snoop
    .snoop_ar_valid_i    (snoop_ar_valid_i),
    .snoop_ar_ready_i    (snoop_ar_ready_i),

    // AXI Read Data Channel Snoop
    .snoop_r_valid_i     (snoop_r_valid_i),
    .snoop_r_ready_i     (snoop_r_ready_i),
    .snoop_r_last_i      (snoop_r_last_i),

    // Activity Output (connected internally)
    .bus_active_o        (bus_active_internal),

    // Completion / outstanding-count probes: unused here (consumed by
    // axi_hang_detector). Left explicitly unconnected.
    .complete_aw_o       (/* UNUSED */),
    .complete_ar_o       (/* UNUSED */),
    .req_count_q_o       (/* UNUSED */)
  );

  ////////////////////////////////////////////////////////////////////////////////
  // Clock Gating Request Instance
  ////////////////////////////////////////////////////////////////////////////////

  prim_cg_req #(
    .DENY_DELAY(DENY_DELAY)
  ) u_cg_req (
    .clk_i        (clk_i),
    .rst_ni       (rst_ni),

    // Activity input (from AXI snoop module)
    .qactive_i    (bus_active_internal),

    // Power Management Interface
    .qaccept_ni   (clk_active_o),
    .qdeny_i      (1'b0), // never deny
    .qreq_no      (qreq_n)
  );

  ////////////////////////////////////////////////////////////////////////////////
  // Clock Gater with Hysteresis Instance
  ////////////////////////////////////////////////////////////////////////////////

  // Convert qreq_n (active low) to enable signal (active high)
  assign cg_enable_internal = !qreq_n;

  prim_clk_gater_hysteresis #(
    .HYST_WIDTH(HYST_WIDTH)
  ) u_clk_gater (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),

    // Activity and control signals
    .busy_i          (bus_active_internal),
    .enable_i        (cg_enable_internal),
    .kick_i          (kick_i),
    .test_clk_en_i   (test_clk_en_i),

    // Hysteresis configuration
    .hysteresis_i    (hysteresis_i),

    // Clock outputs
    .clk_active_o    (clk_active_o),
    .gated_clk_o     (gated_clk_o)
  );

  ////////////////////////////////////////////////////////////////////////////////
  // Output Assignments
  ////////////////////////////////////////////////////////////////////////////////

  // Expose internal bus activity signal as module output
  assign bus_active_o = bus_active_internal;

  ////////////////////////////////////////////////////////////////////////////////
  // Assertions
  ////////////////////////////////////////////////////////////////////////////////

  // Only validate top-level interface signals that aren't already checked by sub-modules
  // Sub-modules handle their own input validation

  // Validate clock gating interface (new signals not validated by sub-modules)
  `OCAH_OT_ASSERT_KNOWN(KickKnown_A, kick_i, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(TestClkEnKnown_A, test_clk_en_i, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(HysteresisKnown_A, hysteresis_i, clk_i, !rst_ni)

  // Validate that hysteresis value is within reasonable bounds
  `OCAH_OT_ASSERT(HysteresisBounds_A, hysteresis_i <= {HYST_WIDTH{1'b1}}, clk_i, !rst_ni)

  // Validate output signals consistency
  `OCAH_OT_ASSERT_KNOWN(ClkActiveKnown_A, clk_active_o, clk_i, !rst_ni)
  `OCAH_OT_ASSERT_KNOWN(BusActiveKnown_A, bus_active_o, clk_i, !rst_ni)

  // Functional relationship checks
  `OCAH_OT_ASSERT(ActivityConsistency_A, bus_active_o == bus_active_internal, clk_i, !rst_ni)

endmodule
