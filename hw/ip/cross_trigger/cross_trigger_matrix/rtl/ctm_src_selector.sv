// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Matrix Source Selector Module
//
// Description:
// Implements the selection and OR logic for a single CT_Src output port.
// Selects which CT_Dst inputs to forward based on the select mask, then ORs
// them together. The output is registered to prevent glitches.
//------------------------------------------------------------------------------


module ctm_src_selector #(
  parameter int unsigned NUM_CT_DST = 4
) (
  // Clock and Reset
  input  logic                    clk_i,
  input  logic                    rst_ni,

  // CT_Dst input pulses
  input  logic [NUM_CT_DST-1:0]   ct_dst_i,

  // Selection mask from register (each bit enables corresponding CT_Dst)
  input  logic [NUM_CT_DST-1:0]   select_i,

  // CT_Src output pulse (registered)
  output logic                    ct_src_o
);

  // Combinatorial logic: AND each CT_Dst with its select bit, then OR all together
  logic ct_src_comb;

  // Generate AND gates for each CT_Dst with its select bit
  logic [NUM_CT_DST-1:0] selected_pulses;
  genvar i;
  generate
    for (i = 0; i < NUM_CT_DST; i++) begin : gen_select
      assign selected_pulses[i] = ct_dst_i[i] & select_i[i];
    end
  endgenerate

  // OR all selected pulses together
  assign ct_src_comb = |selected_pulses;

  // Register the output to prevent glitches
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ct_src_o <= 1'b0;
    end else begin
      ct_src_o <= ct_src_comb;
    end
  end

endmodule : ctm_src_selector

