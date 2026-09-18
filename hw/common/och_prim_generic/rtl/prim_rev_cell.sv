// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// REV Cell
//
//--------------------------------------------------
module prim_rev_cell (
  output logic [7:0] lo_o,
  output logic [7:0] hi_o,
  input  logic [7:0] in_i,
  output logic [7:0] out_o,
  input logic src_low_i,
  input logic src_high_i
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
