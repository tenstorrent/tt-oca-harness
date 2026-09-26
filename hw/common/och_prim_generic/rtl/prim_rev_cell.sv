// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Fan constant straps and a pass-through data bus.
//
// Drive every bit of lo_o from src_low_i and every bit of hi_o from src_high_i, and copy
// in_i to out_o. Use this to build netlist-visible constant and revision straps.

module prim_rev_cell (
  output logic [7:0] lo_o,      // All bits tied to src_low_i.
  output logic [7:0] hi_o,      // All bits tied to src_high_i.
  input  logic [7:0] in_i,      // Pass-through data into out_o.
  output logic [7:0] out_o,     // Copy of in_i.
  input logic src_low_i,        // Constant sourced onto lo_o.
  input logic src_high_i        // Constant sourced onto hi_o.
);
  integer i;

  always_comb begin
    for (i = 0; i < 8; i++) begin
      lo_o[i] = src_low_i;
      hi_o[i] = src_high_i;
      out_o[i] = in_i[i];
    end
  end

endmodule
/* an example for instantiate this module
 tt_rev_cell #(
 .WIDTH(8)
 ) sep_sec_disable(
 .lo_o(low[7:0]),
 .hi_o(high[7:0]),
 .in_i({low[7],low[6], low[5], low[4], low[3], low[2], low[1], high[0]}),
 .out_o(d_out[7:0]),
 .src_low_i(1'b0),
 .src_high_i(1'b1)
 )

 */
