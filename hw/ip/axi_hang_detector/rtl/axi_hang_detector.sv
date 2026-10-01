// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Detect stalled AXI traffic and raise a level interrupt when a hang persists.
//
// Monitors an AXI bus via an internally instantiated prim_axi_snoop.
// Counts cycles with outstanding transactions and no completion; when the counter reaches
// the SW-programmable threshold, asserts irq_o. The threshold is loaded whenever the
// detector is disabled, the bus is idle or a transaction completes, so a new value takes
// effect at the next stall window, and a threshold of zero disables detection.
// irq_o is a direct combinational level with no status latch, gated by enable_i and
// irq_en_i.
// irq_test_i forces irq_o high for firmware bring-up without a real bus stall, while enable_i
// and irq_en_i are set.
// Configuration inputs are in the clk_i domain; in smc_base they come from the
// smc_base_config register block.

`include "prim_assert.sv"

module axi_hang_detector #(
  parameter int unsigned OUTSTANDING_TX = 6  // Max outstanding tracked by the snoop.
) (
  input  logic           clk_i,                             // System clock.
  input  logic           rst_ni,                            // Async reset, active-low.

  input  logic           snoop_aw_valid_i,                  // Snooped AW valid (same as
                                                            // prim_axi_snoop).
  input  logic           snoop_aw_ready_i,                  // Snooped AW ready.
  input  logic           snoop_w_valid_i,                   // Snooped W valid.
  input  logic           snoop_b_valid_i,                   // Snooped B valid.
  input  logic           snoop_b_ready_i,                   // Snooped B ready.
  input  logic           snoop_ar_valid_i,                  // Snooped AR valid.
  input  logic           snoop_ar_ready_i,                  // Snooped AR ready.
  input  logic           snoop_r_valid_i,                   // Snooped R valid.
  input  logic           snoop_r_ready_i,                   // Snooped R ready.
  input  logic           snoop_r_last_i,                    // Snooped R last.

  input  logic           enable_i,                          // CTRL.enable; detector enable. Low
                                                            // reloads the counter and holds irq_o
                                                            // low.
  input  logic           irq_en_i,                          // CTRL.irq_en; interrupt enable.
  input  logic           irq_test_i,                        // CTRL.irq_test; forces irq_o while
                                                            // enable_i and irq_en_i are set.
  input  logic [19:0]    threshold_i,                       // TIMEOUT_THRESHOLD.value; stalled
                                                            // clk_i cycles before irq_o asserts;
                                                            // zero disables detection.

  output logic           bus_active_o,                      // Pass-through bus_active from the
                                                            // snoop.

  output logic           irq_o                              // Hang interrupt as a direct
                                                            // combinational level. Asserts when
                                                            // enable_i and irq_en_i are set and
                                                            // either the stall counter reaches
                                                            // threshold_i or irq_test_i is set.
);

  /////////////////////////////
  // Snoop instance + probes //
  /////////////////////////////

  // Counter width derived the same way prim_axi_snoop derives it
  localparam int unsigned ReqCountW = (OUTSTANDING_TX > 1) ? $clog2(OUTSTANDING_TX) + 2 : 2;

  logic complete_aw, complete_ar, any_completion;
  logic [ReqCountW-1:0]       req_count_q;
  logic                       req_count_nonzero;

  prim_axi_snoop #(
    .OUTSTANDING_TX(OUTSTANDING_TX)
  ) u_prim_axi_snoop (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .snoop_aw_valid_i(snoop_aw_valid_i),
    .snoop_aw_ready_i(snoop_aw_ready_i),
    .snoop_w_valid_i (snoop_w_valid_i),
    .snoop_b_valid_i (snoop_b_valid_i),
    .snoop_b_ready_i (snoop_b_ready_i),
    .snoop_ar_valid_i(snoop_ar_valid_i),
    .snoop_ar_ready_i(snoop_ar_ready_i),
    .snoop_r_valid_i (snoop_r_valid_i),
    .snoop_r_ready_i (snoop_r_ready_i),
    .snoop_r_last_i  (snoop_r_last_i),
    .bus_active_o    (bus_active_o),
    .complete_aw_o   (complete_aw),
    .complete_ar_o   (complete_ar),
    .req_count_q_o   (req_count_q)
  );

  assign any_completion    = complete_aw | complete_ar;
  assign req_count_nonzero = |req_count_q;


  ////////////////////////////////////
  // Down-counting timeout counter  //
  ////////////////////////////////////
  //
  // The threshold is latched when a stall window starts: the counter (re)loads
  // threshold while the bus is idle/making progress, counts down each stalled
  // cycle, and fires (a level) on reaching 0. detect_armed_q latches alongside
  // it, so a threshold written mid-window cannot change that window's outcome.

  logic [19:0] stall_cnt_q;
  logic        detect_armed_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      // Max value (non-zero) so the compare-to-zero below does not read as
      // "fired" during/just after reset; reloaded to threshold on the
      // first idle cycle.
      stall_cnt_q    <= 20'hF_FFFF;
      detect_armed_q <= 1'b0;
    end else if (!enable_i || !req_count_nonzero || any_completion) begin
      // Idle / making progress: (re)arm by loading the threshold.
      stall_cnt_q    <= threshold_i;
      detect_armed_q <= |threshold_i;
    end else if (|stall_cnt_q) begin
      // Outstanding tx with no completion: count down toward the timeout.
      stall_cnt_q <= stall_cnt_q - 20'd1;
    end
    // else: reached 0 (timed out) — hold until the bus recovers
  end

  // Level: high once the counter has counted down to 0 (bus still hung).
  // Drops naturally when a completion or !enable reloads the counter.
  // threshold == 0 disables detection: detect_armed_q is low for that window, so
  // the counter sitting at 0 with nothing to count does not read as fired.
  logic timeout_active;
  assign timeout_active = enable_i && detect_armed_q && (stall_cnt_q == 20'd0);


  ///////////////////////////////
  // Form interrupt output     //
  ///////////////////////////////
  //
  // Direct combinational level — no status latch. irq_o stays high while the
  // bus remains hung (stall_cnt saturated) or irq_test is held, gated by
  // enable and irq_en.

  assign irq_o = enable_i & irq_en_i & (timeout_active | irq_test_i);


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)
  `OCAH_OT_ASSERT_KNOWN(BusActiveKnownO_A, bus_active_o)
  `OCAH_OT_ASSERT_INIT(ParamOutstandingTx_A, OUTSTANDING_TX >= 1)

endmodule
