// SPDX-License-Identifier: Apache-2.0
//
// Compatibility stub for prim_sync2 during public Verilator builds.
//
// The public primitive library exposes prim_flop_2sync with lowRISC-style
// ports, so this wrapper keeps DTP DUT elaboration independent of any
// non-public primitive port naming. Extend tb/verilator_stubs/ with additional
// behavioral stubs (e.g. tech cells) as the DTP build surfaces them.

module prim_sync2 #(
    parameter int unsigned WIDTH                  = 1,
    parameter bit          RANDOM_DELAY_GRAY_CODE = 1'b0
) (
    input  logic             i_clk,
    input  logic [WIDTH-1:0] i_d,
    output logic [WIDTH-1:0] o_q
);

    prim_flop_2sync #(
        .Width(WIDTH)
    ) u_sync2 (
        .clk_i  (i_clk),
        .rst_ni (1'b1),
        .d_i    (i_d),
        .q_o    (o_q)
    );

endmodule
