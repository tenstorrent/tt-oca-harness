// SPDX-License-Identifier: Apache-2.0
//
// Simulation POR initializer for OpenTitan `prim_flop`.
//
// The upstream module
// (vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv)
// has no power-on value. An async-reset flop whose `rst_ni` is already 0 at t=0
// never sees a negedge and stays X. PeakRDL immediate asserts in the `always_ff`
// else then treat `if (~arst_n)` as false and fire at 0 fs.
//
// Sequential behaviour after the first clock or reset edge is identical to
// upstream. A declaration initializer or `initial` on the same net as
// `always_ff` trips VCS ICPD / ICPD_INIT, so POR is a one-shot flag: `q_o`
// presents `ResetValue` until that edge, then follows `q_q` with no X-mask.
// Selected via `[build].exclude_files` + `sources` so every tool compiles this
// definition.
//
// Two consequences of replacing the cell, both checked against this tree:
//
// * `q_o` is a wire fed by a continuous assign here, where upstream drives it
//   from the `always_ff` directly. A hierarchical `force`/`deposit` on a
//   `prim_flop` `q_o` would therefore behave differently. No sequence or test
//   under hw/sys/sep/dv does that today; a future one must target `q_q`.
// * `exclude_files` drops the vendored `prim_generic` definition by path, so any
//   other `prim_flop` reaching the same build would be a MODDUP. This filelist
//   carries no second definition. A flow that composes its own filelist must
//   check the same thing before adding this shim.

module prim_flop #(
    parameter int               Width      = 1,
    parameter logic [Width-1:0] ResetValue = 0
) (
    input                    clk_i,
    input                    rst_ni,
    input        [Width-1:0] d_i,
    output logic [Width-1:0] q_o
);

    logic [Width-1:0] q_q;
    logic             por_done;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        por_done <= 1'b1;
        if (!rst_ni) begin
            q_q <= ResetValue;
        end else begin
            q_q <= d_i;
        end
    end

    // por_done is X until the first clock or reset edge (no initializer: that
    // would be a second driver of an always_ff net). Until then present the
    // async-reset value.
    assign q_o = (por_done === 1'b1) ? q_q : ResetValue;

endmodule
