// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AXI-Lite OKAY responder -- terminates a register interface that has no
// behavioral model behind it. Every access completes with an OKAY response and
// all-zero read data.
//
// Shared by pll_wrap and pvt_wrap, which reserve register interfaces the
// adopter is expected to replace. Keeping one copy means a handshake fix
// reaches both.
//
// The OKAY termination is written out here rather than delegated to
// prim_axi_lite_err_slv. That block wraps axi_err_slv, whose parameter contract
// admits only RESP_DECERR or RESP_SLVERR -- it enforces this with an `initial`
// assertion, so an error slave asked to answer OKAY is a configuration the
// component rejects. The assertion is compiled out under Verilator and fires at
// time 0 on a four-state simulator, which is where the misuse surfaces.
//-----------------------------------------------------------------------------

module smc_axil_okay_responder
  import smc_pkg::*;
#(
    parameter type axil_req_t  = smc_axil_32_32_req_t,
    parameter type axil_resp_t = smc_axil_32_32_resp_t
) (
    input  logic       clk_i,
    input  logic       rst_ni,

    input  axil_req_t  axil_req_i,
    output axil_resp_t axil_resp_o
);

    // One outstanding write and one outstanding read. AW and W are accepted
    // independently and in either order; B is raised once both have landed.
    logic aw_taken_q, w_taken_q, b_valid_q, r_valid_q;

    logic aw_ready, w_ready, ar_ready;
    assign aw_ready = ~aw_taken_q & ~b_valid_q;
    assign w_ready  = ~w_taken_q  & ~b_valid_q;
    assign ar_ready = ~r_valid_q;

    logic aw_hs, w_hs, ar_hs;
    assign aw_hs = axil_req_i.aw_valid & aw_ready;
    assign w_hs  = axil_req_i.w_valid  & w_ready;
    assign ar_hs = axil_req_i.ar_valid & ar_ready;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            aw_taken_q <= 1'b0;
            w_taken_q  <= 1'b0;
            b_valid_q  <= 1'b0;
            r_valid_q  <= 1'b0;
        end else begin
            // The ready terms above hold both AW and W off while B is
            // outstanding, so no handshake can be dropped by the clear below.
            if (b_valid_q) begin
                if (axil_req_i.b_ready) b_valid_q <= 1'b0;
            end else if ((aw_taken_q | aw_hs) & (w_taken_q | w_hs)) begin
                b_valid_q  <= 1'b1;
                aw_taken_q <= 1'b0;
                w_taken_q  <= 1'b0;
            end else begin
                if (aw_hs) aw_taken_q <= 1'b1;
                if (w_hs)  w_taken_q  <= 1'b1;
            end

            if (r_valid_q) begin
                if (axil_req_i.r_ready) r_valid_q <= 1'b0;
            end else if (ar_hs) begin
                r_valid_q <= 1'b1;
            end
        end
    end

    always_comb begin
        axil_resp_o          = '0;
        axil_resp_o.aw_ready = aw_ready;
        axil_resp_o.w_ready  = w_ready;
        axil_resp_o.ar_ready = ar_ready;
        axil_resp_o.b_valid  = b_valid_q;
        axil_resp_o.b.resp   = axi_pkg::RESP_OKAY;
        axil_resp_o.r_valid  = r_valid_q;
        axil_resp_o.r.resp   = axi_pkg::RESP_OKAY;
        axil_resp_o.r.data   = '0;
    end

endmodule
