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
        .i_CK(clk0_i),
        .i_D (~sel_i & !sel_clk1),
        .i_SN(rst_clk0_ni),
        .o_Q (sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r sync_clk0 (
        .i_CK(clk0_i),
        .i_D (~sel_i & !sel_clk1),
        .i_RN(rst_clk0_ni),
        .o_Q (sel_sync_clk0)
      );
    end
  endgenerate

  // Clock 1 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b1) begin : gen_sync_clk1_selected
      prim_flop_4sync_s sync_clk1 (
        .i_CK(clk1_i),
        .i_D (sel_i & !sel_clk0),
        .i_SN(rst_clk1_ni),
        .o_Q (sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r sync_clk1 (
        .i_CK(clk1_i),
        .i_D (sel_i & !sel_clk0),
        .i_RN(rst_clk1_ni),
        .o_Q (sel_sync_clk1)
      );
    end
  endgenerate

  // Clock selection flops - reset behavior based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sel_clk0_selected
      prim_dffsxq clk0_sel (
        .i_CK(clk0_i),
        .i_SN(rst_clk0_ni),
        .i_D (sel_sync_clk0),
        .o_Q (sel_clk0)
      );
      prim_dffrxq clk1_sel (
        .i_CK(clk1_i),
        .i_RN(rst_clk1_ni),
        .i_D (sel_sync_clk1),
        .o_Q (sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_dffrxq clk0_sel (
        .i_CK(clk0_i),
        .i_RN(rst_clk0_ni),
        .i_D (sel_sync_clk0),
        .o_Q (sel_clk0)
      );
      prim_dffsxq clk1_sel (
        .i_CK(clk1_i),
        .i_SN(rst_clk1_ni),
        .i_D (sel_sync_clk1),
        .o_Q (sel_clk1)
      );
    end
  endgenerate

  prim_clkgater clk0_gate (
    .i_clk(clk0_i),
    .i_en(sel_sync_clk0),
    .i_te(test_en_i),
    .o_clk(gated_clk0)
  );

  prim_clkgater clk1_gate (
    .i_clk(clk1_i),
    .i_en(sel_sync_clk1),
    .i_te(test_en_i),
    .o_clk(gated_clk1)
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
