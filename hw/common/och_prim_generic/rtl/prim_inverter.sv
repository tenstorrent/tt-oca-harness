// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//--------------------------------------------------
// Secure Inverter
//
//--------------------------------------------------
module prim_inverter #(
    parameter int unsigned WIDTH = 1
) (
    input  logic [WIDTH-1:0] i_d,
    output logic [WIDTH-1:0] o_q
);

    logic [WIDTH-1:0] inv1;
    logic [WIDTH-1:0] inv2;

    assign inv1 = ~i_d;
    assign inv2 = ~inv1;
    assign o_q = ~inv2;

endmodule
