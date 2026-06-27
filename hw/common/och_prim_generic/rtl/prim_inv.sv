// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//--------------------------------------------------
// Inverter
//
//--------------------------------------------------
module prim_inv  #(
    parameter bit DONT_TOUCH = 1
) (
    input  in_i,
    output out_o
);
  assign out_o = ~in_i;
endmodule



