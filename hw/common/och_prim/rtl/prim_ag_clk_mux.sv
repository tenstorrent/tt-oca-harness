// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AG Clock Mux
//
//--------------------------------------------------
module prim_ag_clk_mux #(
  parameter bit SelectOnReset = 1'b0  // Which clock is selected on reset (0 -> clk0, 1 -> clk1)
) (
  input  logic clk0_i,
  input  logic clk1_i,
  input  logic rst_clk0_ni,
  input  logic rst_clk1_ni,
  input  logic test_en_i,
  input  logic sel_i,
  output logic clk_o
);

  `include "prim_assert.sv"

  logic sel_sync_clk0, sel_sync_clk1;
  logic gated_clk0, gated_clk1;
  logic sel_clk0, sel_clk1;

  // Clock 0 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sync_clk0_selected
      prim_flop_4sync_s sync_clk0 (
        .clk_i(clk0_i),
        .d_i(~sel_i & !sel_clk1),
        .set_ni(rst_clk0_ni),
        .q_o(sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r sync_clk0 (
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
      prim_flop_4sync_s sync_clk1 (
        .clk_i(clk1_i),
        .d_i(sel_i & !sel_clk0),
        .set_ni(rst_clk1_ni),
        .q_o(sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r sync_clk1 (
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
      prim_dffsxq clk0_sel (
        .clk_i(clk0_i),
        .set_ni(rst_clk0_ni),
        .d_i(sel_sync_clk0),
        .q_o(sel_clk0)
      );
      prim_dffrxq clk1_sel (
        .clk_i(clk1_i),
        .rst_ni(rst_clk1_ni),
        .d_i(sel_sync_clk1),
        .q_o(sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_dffrxq clk0_sel (
        .clk_i(clk0_i),
        .rst_ni(rst_clk0_ni),
        .d_i(sel_sync_clk0),
        .q_o(sel_clk0)
      );
      prim_dffsxq clk1_sel (
        .clk_i(clk1_i),
        .set_ni(rst_clk1_ni),
        .d_i(sel_sync_clk1),
        .q_o(sel_clk1)
      );
    end
  endgenerate

  prim_clkgater clk0_gate (
    .clk_i(clk0_i),
    .en_i(sel_sync_clk0),
    .te_i(test_en_i),
    .clk_o(gated_clk0)
  );

  prim_clkgater clk1_gate (
    .clk_i(clk1_i),
    .en_i(sel_sync_clk1),
    .te_i(test_en_i),
    .clk_o(gated_clk1)
  );

  prim_clock_or2 clk_out_or (
    .in0_i(gated_clk0),
    .in1_i(gated_clk1),
    .out_o(clk_o)
  );

  // Mutual exclusion of selected clocks. Disabled while either domain is in
  // reset to avoid X-propagation across asymmetric reset deassertion windows.
  // Sampled in both clock domains so that a brief overlap living between
  // clk0_i edges is still caught by the clk1_i sampler (and vice versa).
  `OCAH_OT_ASSERT(CheckMutualExclusionClk0, !(sel_sync_clk0 && sel_sync_clk1), clk0_i,
                  !(rst_clk0_ni && rst_clk1_ni))
  `OCAH_OT_ASSERT(CheckMutualExclusionClk1, !(sel_sync_clk0 && sel_sync_clk1), clk1_i,
                  !(rst_clk0_ni && rst_clk1_ni))

endmodule
