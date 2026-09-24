// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
`timescale 1ps/1fs

//-----------------------------------------------------------------------------
// PLL Model -- behavioral placeholder for the adopter PLL control/status
// block.
//
// Generates the three SMC/SMU domain clocks as free-running oscillators:
//   clk_ref    100 MHz (10 ns period, fixed)
//   clk_sys    800 MHz (1.25 ns default) or 100 MHz (+pll_sys_period_ns=10)
//   clk_periph 200 MHz (5 ns period, fixed)
//
// The sys period is controlled by the +pll_sys_period_ns plusarg (legal
// values: 1.25 or 10 ns; default 1.25 = 800 MHz).  The other two periods
// are fixed and not configurable.
//
// The AXI-Lite register interface (axil_pll_req_o/resp_i from
// regs/pll_wrap.rdl) is terminated with an OKAY stub; every access
// completes with OKAY and all-zero read data.  A real integration replaces
// this model with the adopter's PLL control/status register block.
//-----------------------------------------------------------------------------

module pll_wrap
  import smc_pkg::*;
#(
  parameter type         axil_req_t    = smc_axil_32_32_req_t,
  parameter type         axil_resp_t   = smc_axil_32_32_resp_t,
  parameter int unsigned SysClkPeriodPs = 1_250
) (
  input  logic       clk_i,
  input  logic       rst_ni,
  input  logic       test_en_i,

  input  axil_req_t  axil_req_i,
  output axil_resp_t axil_resp_o,

  output logic       clk_ref_o,
  output logic       clk_sys_o,
  output logic       clk_periph_o
);

  logic clk_ref, clk_sys, clk_periph;

  assign clk_ref_o    = clk_ref;
  assign clk_sys_o    = clk_sys;
  assign clk_periph_o = clk_periph;

  // 100 MHz reference clock (10 ns = 10000 ps period, fixed).
  initial begin : gen_clk_ref
    clk_ref = 1'b0;
    forever #5000ps clk_ref = ~clk_ref;
  end

  // Sys clock: 800 MHz (1.25 ns) default; override with +pll_sys_period_ns.
  initial begin : gen_clk_sys
    real period_ns;
    real period_ps;
    period_ns = SysClkPeriodPs / 1000.0;
    void'($value$plusargs("pll_sys_period_ns=%f", period_ns));
    if (period_ns != 1.25 && period_ns != 10.0)
      $fatal(1, "pll_wrap +pll_sys_period_ns must be 1.25 or 10, got %g", period_ns);
    period_ps = period_ns * 1000.0;
    clk_sys = 1'b0;
    forever #(period_ps * 0.5) clk_sys = ~clk_sys;
  end

  // 200 MHz peripheral clock (5 ns = 5000 ps period, fixed).
  initial begin : gen_clk_periph
    clk_periph = 1'b0;
    forever #2500ps clk_periph = ~clk_periph;
  end

  // AXI-Lite OKAY stub for the PLL control/status register bank.
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
