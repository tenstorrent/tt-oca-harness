// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mask CT_Dst inputs with a select vector, OR them, and register the CT_Src pulse.
//
// select_i enables which destinations contribute; registration prevents glitches on
// ct_src_o.

module ctm_src_selector #(
  parameter int unsigned NUM_CT_DST = 4  // CT_Dst input count.
) (
  input  logic                    clk_i,  // System clock.
  input  logic                    rst_ni,  // Active-low reset.

  input  logic [NUM_CT_DST-1:0]   ct_dst_i,  // Cross-trigger dst.

  input  logic [NUM_CT_DST-1:0]   select_i,  // Select.

  output logic                    ct_src_o  // Cross-trigger src.
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

