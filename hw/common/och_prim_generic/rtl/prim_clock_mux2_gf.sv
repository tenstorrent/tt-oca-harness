// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mux clk0_i and clk1_i onto clk_o without glitches.
//
// Synchronize sel_i into each source domain, gate the deselected clock off before
// enabling the other, and NAND-combine the gated clocks onto clk_o. SelectOnReset chooses
// which clock is enabled while rst_ni is asserted: 0 selects clk0_i during reset, 1
// selects clk1_i.

module prim_clock_mux2_gf #(
  parameter bit SelectOnReset = 1'b0  // 0 selects clk0_i during reset; 1 selects clk1_i.
) (
  input  logic clk0_i,  // First clock source.
  input  logic clk1_i,  // Second clock source.
  input  logic rst_ni,  // Active-low reset for the select synchronizers.
  input  logic sel_i,   // Selects clk1_i when high, clk0_i when low.
  output logic clk_o    // Glitch-free muxed clock.
);
  logic sel_sync_clk0, sel_sync_clk1;
  logic gated_clk0, gated_clk1;
  logic inv_clk0, inv_clk1;
  logic sel_clk0, sel_clk1;

  // Clock 0 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sync_clk0_selected
      prim_flop_4sync_s u_sync_clk0 (
        .d_i(~sel_i & !sel_clk1),
        .clk_i(clk0_i),
        .set_ni(rst_ni),
        .q_o(sel_sync_clk0)
      );
    end else begin : gen_sync_clk0_not_selected
      prim_flop_4sync_r u_sync_clk0 (
        .d_i(~sel_i & !sel_clk1),
        .clk_i(clk0_i),
        .rst_ni(rst_ni),
        .q_o(sel_sync_clk0)
      );
    end
  endgenerate

  // Clock 1 synchronizer - resets to selected state based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b1) begin : gen_sync_clk1_selected
      prim_flop_4sync_s u_sync_clk1 (
        .d_i(sel_i & !sel_clk0),
        .clk_i(clk1_i),
        .set_ni(rst_ni),
        .q_o(sel_sync_clk1)
      );
    end else begin : gen_sync_clk1_not_selected
      prim_flop_4sync_r u_sync_clk1 (
        .d_i(sel_i & !sel_clk0),
        .clk_i(clk1_i),
        .rst_ni(rst_ni),
        .q_o(sel_sync_clk1)
      );
    end
  endgenerate

  prim_clock_inv u_clk0_inv (
    .clk_i(clk0_i),
    .scanmode_i(1'b0),
    .clk_no(inv_clk0)
  );

  prim_clock_inv u_clk1_inv (
    .clk_i(clk1_i),
    .scanmode_i(1'b0),
    .clk_no(inv_clk1)
  );

  // Clock selection flops - reset behavior based on SelectOnReset parameter
  generate
    if (SelectOnReset == 1'b0) begin : gen_sel_clk0_selected
      prim_dffsxq u_clk0_sel (
        .clk_i(inv_clk0),
        .set_ni(rst_ni),
        .d_i(sel_sync_clk0),
        .q_o(sel_clk0)
      );
      prim_dffrxq u_clk1_sel (
        .clk_i(inv_clk1),
        .rst_ni(rst_ni),
        .d_i(sel_sync_clk1),
        .q_o(sel_clk1)
      );
    end else begin : gen_sel_clk1_selected
      prim_dffrxq u_clk0_sel (
        .clk_i(inv_clk0),
        .rst_ni(rst_ni),
        .d_i(sel_sync_clk0),
        .q_o(sel_clk0)
      );
      prim_dffsxq u_clk1_sel (
        .clk_i(inv_clk1),
        .set_ni(rst_ni),
        .d_i(sel_sync_clk1),
        .q_o(sel_clk1)
      );
    end
  endgenerate

  prim_clock_nand2 u_clk0_gate (
    .a1_i(clk0_i),
    .a2_i(sel_clk0),
    .y_o (gated_clk0)
  );

  prim_clock_nand2 u_clk1_gate (
    .a1_i(clk1_i),
    .a2_i(sel_clk1),
    .y_o (gated_clk1)
  );

  prim_clock_nand2 u_clk_out_nd (
    .a1_i(gated_clk0),
    .a2_i(gated_clk1),
    .y_o (clk_o)
  );

endmodule
