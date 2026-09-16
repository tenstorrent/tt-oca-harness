// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AG Clock Mux
//
//--------------------------------------------------
module prim_ag_clk_mux #(
  parameter bit SelectOnReset = 1'b0  // Which clock is selected on reset (0 -> clk0, 1 -> clk1)
) (
  input  logic i_clk0,
  input  logic i_clk1,
  input  logic i_reset_n_clk0,
  input  logic i_reset_n_clk1,
  input  logic i_test_en,
  input  logic i_sel,
  output logic o_clk
);

  `include "prim_assert.sv"

  logic sel_sync_clk0, sel_sync_clk1;
  logic gated_clk0, gated_clk1;
  logic sel_clk0, sel_clk1;

  // Clock 0 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sync_clk0_selected
      prim_flop_4sync_s sync_clk0 (
        .i_CK(i_clk0),
        .i_D (~i_sel & !sel_clk1),
        .i_SN(i_reset_n_clk0),
        .o_Q (sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r sync_clk0 (
        .i_CK(i_clk0),
        .i_D (~i_sel & !sel_clk1),
        .i_RN(i_reset_n_clk0),
        .o_Q (sel_sync_clk0)
      );
    end
  endgenerate

  // Clock 1 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b1) begin : gen_sync_clk1_selected
      prim_flop_4sync_s sync_clk1 (
        .i_CK(i_clk1),
        .i_D (i_sel & !sel_clk0),
        .i_SN(i_reset_n_clk1),
        .o_Q (sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r sync_clk1 (
        .i_CK(i_clk1),
        .i_D (i_sel & !sel_clk0),
        .i_RN(i_reset_n_clk1),
        .o_Q (sel_sync_clk1)
      );
    end
  endgenerate

  // Clock selection flops - reset behavior based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sel_clk0_selected
      prim_dffsxq clk0_sel (
        .i_CK(i_clk0),
        .i_SN(i_reset_n_clk0),
        .i_D (sel_sync_clk0),
        .o_Q (sel_clk0)
      );
      prim_dffrxq clk1_sel (
        .i_CK(i_clk1),
        .i_RN(i_reset_n_clk1),
        .i_D (sel_sync_clk1),
        .o_Q (sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_dffrxq clk0_sel (
        .i_CK(i_clk0),
        .i_RN(i_reset_n_clk0),
        .i_D (sel_sync_clk0),
        .o_Q (sel_clk0)
      );
      prim_dffsxq clk1_sel (
        .i_CK(i_clk1),
        .i_SN(i_reset_n_clk1),
        .i_D (sel_sync_clk1),
        .o_Q (sel_clk1)
      );
    end
  endgenerate

  prim_clkgater clk0_gate (
    .i_clk(i_clk0),
    .i_en(sel_sync_clk0),
    .i_te(i_test_en),
    .o_clk(gated_clk0)
  );

  prim_clkgater clk1_gate (
    .i_clk(i_clk1),
    .i_en(sel_sync_clk1),
    .i_te(i_test_en),
    .o_clk(gated_clk1)
  );

  prim_clock_or2 clk_out_or (
    .in0_i(gated_clk0),
    .in1_i(gated_clk1),
    .out_o(o_clk)
  );

  // Mutual exclusion of selected clocks. Disabled while either domain is in
  // reset to avoid X-propagation across asymmetric reset deassertion windows.
  // Sampled in both clock domains so that a brief overlap living between
  // i_clk0 edges is still caught by the i_clk1 sampler (and vice versa).
  `OCAH_OT_ASSERT(CheckMutualExclusionClk0, !(sel_sync_clk0 && sel_sync_clk1), i_clk0,
                  !(i_reset_n_clk0 && i_reset_n_clk1))
  `OCAH_OT_ASSERT(CheckMutualExclusionClk1, !(sel_sync_clk0 && sel_sync_clk1), i_clk1,
                  !(i_reset_n_clk0 && i_reset_n_clk1))

endmodule
