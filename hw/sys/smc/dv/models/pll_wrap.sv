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
// values: 1.25 or 10 ns; default 1.25 = 800 MHz).  The ref and periph
// periods are fixed and not configurable via plusarg.
//
// For sys and periph, each oscillator passes through a prim_clock_mux2
// (test-mode bypass) then a prim_ag_clk_mux (glitch-free output) before
// reaching the output port.  sel=0 on both muxes keeps the PLL oscillator
// path.  ag_rst_n starts high for 1 ps then tracks rst_ni; the falling
// edge initialises the AG mux set/reset flops before functional reset
// deasserts.  clk_ref passes straight through -- no mux needed.
//
// The AXI-Lite register interface (axil_pll_req_o/resp_i from
// regs/pll_wrap.rdl) is terminated with an OKAY stub.  A real integration
// replaces this model with the adopter's PLL control/status register block.
//-----------------------------------------------------------------------------

module pll_wrap
  import smc_pkg::*;
#(
  parameter type         axil_req_t     = smc_axil_32_32_req_t,
  parameter type         axil_resp_t    = smc_axil_32_32_resp_t,
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

  ///////////////
  // Oscillators
  ///////////////

  logic osc_ref, osc_sys, osc_periph;

  // 100 MHz reference clock (10 ns = 10000 ps period, fixed).
  initial begin : gen_clk_ref
    osc_ref = 1'b0;
    forever #5000ps osc_ref = ~osc_ref;
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
    osc_sys = 1'b0;
    forever #(period_ps * 0.5) osc_sys = ~osc_sys;
  end

  // 200 MHz peripheral clock (5 ns = 5000 ps period, fixed).
  initial begin : gen_clk_periph
    osc_periph = 1'b0;
    forever #2500ps osc_periph = ~osc_periph;
  end

  ///////////////
  // AG reset
  ///////////////

  // Starts high for 1 ps so the AG mux set/reset flops receive a falling
  // edge from their rst/set pins before functional reset deasserts.
  logic ag_rst_n = 1'b1;
  always @(rst_ni) ag_rst_n <= #1ps rst_ni;

  /////////////////////////////
  // ref -- straight through
  /////////////////////////////

  assign clk_ref_o = osc_ref;

  /////////////////////////////
  // sys -- mux chain
  /////////////////////////////

  logic clk_sys_mux2;

  prim_clock_mux2 u_sys_clk_mux2 (
    .clk0_i (osc_sys),
    .clk1_i (osc_sys),
    .sel_i  (test_en_i),
    .clk_o  (clk_sys_mux2)
  );

  prim_ag_clk_mux #(
    .SelectOnReset (1'b0)
  ) u_sys_ag_mux (
    .clk0_i     (clk_sys_mux2),
    .clk1_i     (osc_sys),
    .rst_clk0_ni(ag_rst_n),
    .rst_clk1_ni(ag_rst_n),
    .test_en_i  (test_en_i),
    .sel_i      (1'b0),
    .clk_o      (clk_sys_o)
  );

  /////////////////////////////
  // periph -- mux chain
  /////////////////////////////

  logic clk_periph_mux2;

  prim_clock_mux2 u_periph_clk_mux2 (
    .clk0_i (osc_periph),
    .clk1_i (osc_periph),
    .sel_i  (test_en_i),
    .clk_o  (clk_periph_mux2)
  );

  prim_ag_clk_mux #(
    .SelectOnReset (1'b0)
  ) u_periph_ag_mux (
    .clk0_i     (clk_periph_mux2),
    .clk1_i     (osc_periph),
    .rst_clk0_ni(ag_rst_n),
    .rst_clk1_ni(ag_rst_n),
    .test_en_i  (test_en_i),
    .sel_i      (1'b0),
    .clk_o      (clk_periph_o)
  );

  ////////////////////
  // AXI-Lite stub
  ////////////////////

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
