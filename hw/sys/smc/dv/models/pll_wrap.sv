// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// PLL Model -- behavioral placeholder for the adopter PLL control/status
// block.
//
// smc.sv's PLL clocks (clk_smc_i/clk_ref_i/clk_periph_i) arrive
// pre-generated at the OCAH boundary; this model terminates the
// axil_pll_req_o/resp_i register interface reserved by regs/pll_wrap.rdl.
// Every access completes with an OKAY response and all-zero read data,
// through axil_okay_slv. A real integration replaces this with the adopter's
// PLL control/status register block.
//-----------------------------------------------------------------------------

module pll_wrap
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

  axil_okay_slv #(
    .axil_req_t  (axil_req_t),
    .axil_resp_t (axil_resp_t),
    .RESP_WIDTH  (smc_pkg::AXI_LITE_32_DATA_WIDTH),
    .RESP_DATA   ('0)
  ) u_axil_okay_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .axil_req_i (axil_req_i),
    .axil_resp_o(axil_resp_o)
  );

endmodule
