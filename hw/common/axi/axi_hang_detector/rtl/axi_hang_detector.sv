// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AXI Hang Detector
//
// Monitors an AXI bus via an internally instantiated prim_axi_snoop. Counts
// cycles during which transactions are outstanding without seeing any
// completion; when the counter reaches a SW-programmable threshold, asserts
// irq_o. The interrupt is a direct combinational level (no status latch) gated
// by the enable and irq_en config bits. irq_test forces irq_o high for firmware
// bring-up without needing a real bus stall.
//
// Copyright 2026 Tenstorrent Inc.
//-----------------------------------------------------------------------------

`include "prim_assert.sv"

module axi_hang_detector #(
  parameter int unsigned OutstandingTx = 6
) (
  // Global interface
  input  logic           clk_i,
  input  logic           rst_ni,

  // AXI snoop inputs (same as prim_axi_snoop)
  input  logic           snoop_aw_valid_i,
  input  logic           snoop_aw_ready_i,
  input  logic           snoop_w_valid_i,
  input  logic           snoop_b_valid_i,
  input  logic           snoop_b_ready_i,
  input  logic           snoop_ar_valid_i,
  input  logic           snoop_ar_ready_i,
  input  logic           snoop_r_valid_i,
  input  logic           snoop_r_ready_i,
  input  logic           snoop_r_last_i,

  // Configuration (from cpu_ctrl register block, clk_i domain)
  input  logic           enable_i,      // CTRL.enable
  input  logic           irq_en_i,      // CTRL.irq_en
  input  logic           irq_test_i,    // CTRL.irq_test
  input  logic [19:0]    threshold_i,   // TIMEOUT_THRESHOLD.value

  // Pass-through bus_active from snoop
  output logic           bus_active_o,

  // Interrupt output: direct combinational level.
  // Asserts when enable & irq_en are set and the stall counter reaches
  // threshold, or when irq_test is set for verification.
  output logic           irq_o
);

  /////////////////////////////
  // Snoop instance + probes //
  /////////////////////////////

  // Counter width derived the same way prim_axi_snoop derives it
  localparam int unsigned ReqCountW = (OutstandingTx > 1) ? $clog2(OutstandingTx) + 2 : 2;

  logic complete_aw, complete_ar, any_completion;
  logic [ReqCountW-1:0]       req_count_q;
  logic                       req_count_nonzero;

  prim_axi_snoop #(
    .OutstandingTx(OutstandingTx)
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
  // cycle, and fires (a level) on reaching 0.

  logic [19:0] stall_cnt_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      // Max value (non-zero) so the compare-to-zero below does not read as
      // "fired" during/just after reset; reloaded to threshold on the
      // first idle cycle.
      stall_cnt_q <= 20'hF_FFFF;
    end else if (!enable_i || !req_count_nonzero || any_completion) begin
      // Idle / making progress: (re)arm by loading the threshold.
      stall_cnt_q <= threshold_i;
    end else if (stall_cnt_q != 20'd0) begin
      // Outstanding tx with no completion: count down toward the timeout.
      stall_cnt_q <= stall_cnt_q - 20'd1;
    end
    // else: reached 0 (timed out) — hold until the bus recovers
  end

  // Level: high once the counter has counted down to 0 (bus still hung).
  // Drops naturally when a completion or !enable reloads the counter.
  // threshold == 0 disables detection: the loaded value 0 would read as fired
  // immediately, so guard it off.
  logic timeout_active;
  assign timeout_active = enable_i && (threshold_i != 20'd0)
                                     && (stall_cnt_q == 20'd0);


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
  `OCAH_OT_ASSERT_INIT(ParamOutstandingTx_A, OutstandingTx >= 1)

endmodule
