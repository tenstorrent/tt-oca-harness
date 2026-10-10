// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mask CT_Dst inputs with a select vector, OR them, and register the CT_Src pulse.
//
// select_i enables which destinations contribute; registration prevents glitches on
// ct_src_o.

`include "ocah_registers.svh"

module ctm_src_selector #(
  parameter int unsigned NUM_CT_DST = 4  // CT_Dst input count.
) (
  input  logic                    clk_i,  // System clock.
  input  logic                    rst_ni,  // Active-low asynchronous reset; clears ct_src_o.

  input  logic [NUM_CT_DST-1:0]   ct_dst_i,  // Cross-trigger pulses from every CT_Dst port, one bit
                                             // per port.

  input  logic [NUM_CT_DST-1:0]   select_i,  // Per-destination enable mask from this CT_Src's
                                             // CT_DST_SELECT field; bit i admits ct_dst_i[i] into
                                             // the OR.

  output logic                    ct_src_o  // OR of the selected ct_dst_i bits, registered on
                                            // clk_i; one cycle of latency.
);

  // Combinatorial logic: AND each CT_Dst with its select bit, then OR all together
  logic ct_src_comb;

  // Generate AND gates for each CT_Dst with its select bit
  logic [NUM_CT_DST-1:0] selected_pulses;
  for (genvar i = 0; i < NUM_CT_DST; i++) begin : gen_select
    assign selected_pulses[i] = ct_dst_i[i] & select_i[i];
  end

  // OR all selected pulses together
  assign ct_src_comb = |selected_pulses;

  // Register the output to prevent glitches
  `OCAH_FF(ct_src_o, ct_src_comb, 1'b0, clk_i, rst_ni)

endmodule : ctm_src_selector

