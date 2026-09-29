// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mux clk0_i and clk1_i onto clk_o without glitches.
//
// Synchronize sel_i into each source domain, gate the deselected clock off before enabling
// the other, and combine the gated clocks onto clk_o.
// SelectOnReset chooses which clock is enabled while reset is asserted: 0 selects clk0_i
// during reset, 1 selects clk1_i.
// test_en_i forces both clock gates open, so clk_o is the OR of clk0_i and clk1_i.

module prim_ag_clk_mux #(
  parameter bit SelectOnReset = 1'b0  // 0 selects clk0_i during reset; 1 selects clk1_i.
) (
  input  logic clk0_i,  // First clock source.
  input  logic clk1_i,  // Second clock source.
  input  logic rst_clk0_ni,  // Async active-low reset in the clk0_i domain.
  input  logic rst_clk1_ni,  // Async active-low reset in the clk1_i domain.
  input  logic test_en_i,  // Scan/test enable; forces both clock gates open.
  input  logic sel_i,  // Selects clk1_i when high, clk0_i when low; asynchronous,
                       // synchronized into each clock domain through four flops.
  output logic clk_o  // Glitch-free muxed clock.
);

  `include "prim_assert.sv"

  logic sel_sync_clk0, sel_sync_clk1;
  logic gated_clk0, gated_clk1;
  logic sel_clk0, sel_clk1;

  // Clock 0 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sync_clk0_selected
      prim_flop_4sync_s u_sync_clk0 (
        .clk_i(clk0_i),
        .d_i(~sel_i & !sel_clk1),
        .set_ni(rst_clk0_ni),
        .q_o(sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r u_sync_clk0 (
        .clk_i(clk0_i),
        .d_i(~sel_i & !sel_clk1),
        .rst_ni(rst_clk0_ni),
        .q_o(sel_sync_clk0)
      );
    end
  endgenerate

  // Clock 1 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b1) begin : gen_sync_clk1_selected
      prim_flop_4sync_s u_sync_clk1 (
        .clk_i(clk1_i),
        .d_i(sel_i & !sel_clk0),
        .set_ni(rst_clk1_ni),
        .q_o(sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r u_sync_clk1 (
        .clk_i(clk1_i),
        .d_i(sel_i & !sel_clk0),
        .rst_ni(rst_clk1_ni),
        .q_o(sel_sync_clk1)
      );
    end
  endgenerate

  // Clock selection flops - reset behavior based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sel_clk0_selected
      prim_flop #(
        .ResetValue(1'b1)
      ) u_clk0_sel (
        .clk_i(clk0_i),
        .rst_ni(rst_clk0_ni),
        .d_i(sel_sync_clk0),
        .q_o(sel_clk0)
      );
      prim_flop u_clk1_sel (
        .clk_i(clk1_i),
        .rst_ni(rst_clk1_ni),
        .d_i(sel_sync_clk1),
        .q_o(sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_flop u_clk0_sel (
        .clk_i(clk0_i),
        .rst_ni(rst_clk0_ni),
        .d_i(sel_sync_clk0),
        .q_o(sel_clk0)
      );
      prim_flop #(
        .ResetValue(1'b1)
      ) u_clk1_sel (
        .clk_i(clk1_i),
        .rst_ni(rst_clk1_ni),
        .d_i(sel_sync_clk1),
        .q_o(sel_clk1)
      );
    end
  endgenerate

  prim_clock_gating u_clk0_gate (
    .clk_i(clk0_i),
    .en_i(sel_sync_clk0),
    .test_en_i(test_en_i),
    .clk_o(gated_clk0)
  );

  prim_clock_gating u_clk1_gate (
    .clk_i(clk1_i),
    .en_i(sel_sync_clk1),
    .test_en_i(test_en_i),
    .clk_o(gated_clk1)
  );

  assign clk_o = gated_clk0 | gated_clk1;

  // Mutual exclusion of selected clocks. Disabled while either domain is in
  // reset to avoid X-propagation across asymmetric reset deassertion windows.
  // Sampled in both clock domains so that a brief overlap living between
  // clk0_i edges is still caught by the clk1_i sampler (and vice versa).
  `OCAH_OT_ASSERT(CheckMutualExclusionClk0, !(sel_sync_clk0 && sel_sync_clk1), clk0_i,
                  !(rst_clk0_ni && rst_clk1_ni))
  `OCAH_OT_ASSERT(CheckMutualExclusionClk1, !(sel_sync_clk0 && sel_sync_clk1), clk1_i,
                  !(rst_clk0_ni && rst_clk1_ni))

endmodule
