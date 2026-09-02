// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// PVT Model -- behavioral placeholder for the adopter PVT sensor block.
//
// Terminates the axil_pvt_req_o/resp_i register interface reserved by
// regs/pvt_wrap.rdl. Every access completes with an OKAY response and
// all-zero read data (e.g. a temperature/voltage-status poll reads back as "no
// alarm"). A real integration replaces this with the adopter's PVT sensor
// control/status register block.
//-----------------------------------------------------------------------------

module pvt_wrap
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

    smc_axil_okay_responder #(
        .axil_req_t (axil_req_t),
        .axil_resp_t(axil_resp_t)
    ) u_okay_responder (
        .clk_i,
        .rst_ni,
        .axil_req_i,
        .axil_resp_o
    );

endmodule
