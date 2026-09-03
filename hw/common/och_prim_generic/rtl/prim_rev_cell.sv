// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// REV Cell
//
//--------------------------------------------------
module prim_rev_cell (
  output logic [7:0] LO,
  output logic [7:0] HI,
  input  logic [7:0] IN,
  output logic [7:0] OUT,
  input logic SRC_LOW,
  input logic SRC_HIGH
);

  integer i;

  always_comb begin
    for (i = 0; i < 8; i++) begin
      LO[i] = SRC_LOW;
      HI[i] = SRC_HIGH;
      OUT[i] = IN[i];
    end
  end

endmodule
/* an example for instantiate this module
 tt_rev_cell #(
 .WIDTH(8)
 ) sep_sec_disable(
 .LO(low[7:0]),
 .HI(high[7:0]),
 .IN({low[7],low[6], low[5], low[4], low[3], low[2], low[1], high[0]}),
 .OUT(d_out[7:0]),
 .SRC_LOW(1'b0),
 .SRC_HIGH(1'b1)
 )

 */
