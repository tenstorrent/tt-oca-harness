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
// Clock path for sys and periph:
//
//                        clk0 \                         clk0 \
//   osc_ref ─────────────────  prim_clock_mux2          ─────  prim_ag_clk_mux ──> clk_XXX_o
//                        clk1 /  ──> clk_XXX_mux2 ──>   clk1 /
//   osc_XXX ──────────────────   sel=1 (PLL locked)      sel=1 (select PLL path)
//
// prim_clock_mux2 (refclk mux): clk0 is the always-on reference clock and
// clk1 is the PLL oscillator.  In hardware, software holds sel=0 (ref) until
// the PLL has locked, then sets sel=1 to switch to the PLL clock.  In this
// behavioral model the PLL is always considered locked, so sel is hardwired 1.
//
// prim_ag_clk_mux (anti-glitch mux): clk0 is ref (safe fallback on reset,
// SelectOnReset=0) and clk1 is the post-mux2 PLL path.  sel=1 permanently
// selects clk1 in the behavioral model.
//
// clk_ref passes straight through — it is the reference and needs no mux.
//
// The AXI-Lite register interface (axil_pll_req_o/resp_i from
// regs/pll_wrap.rdl) is terminated with an OKAY stub.  A real integration
// replaces this model with the adopter's PLL control/status register block.
//-----------------------------------------------------------------------------

module pll_wrap
  import smc_pkg::*;
#(
  parameter type         axil_req_t     = smc_axil_32_32_req_t,
  parameter type         axil_resp_t    = smc_axil_32_32_resp_t
) (
  input  logic       clk_i,
  input  logic       rst_ni,

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

  // With +pll_osc_bench the model leaves the oscillator nets to the bench,
  // which toggles them at the same periods through hierarchical assigns, and
  // the sys and periph outputs follow the oscillators directly: the clock the
  // bench drives is then the clock the core runs on at every instant, reset
  // included, which the bench's synchronous drivers depend on. The mux chains
  // below are exercised when the model free-runs.
  logic osc_bench;
  initial osc_bench = $test$plusargs("pll_osc_bench");

  // 100 MHz reference clock (10 ns = 10000 ps period, fixed).
  initial begin : gen_clk_ref
    osc_ref = 1'b0;
    if (!osc_bench) forever #5000ps osc_ref = ~osc_ref;
  end

  // Sys clock: 800 MHz (1.25 ns) default; override with +pll_sys_period_ns.
  initial begin : gen_clk_sys
    real period_ns;
    real period_ps;
    period_ns = 1.25;
    void'($value$plusargs("pll_sys_period_ns=%f", period_ns));
    if (period_ns != 1.25 && period_ns != 10.0)
      $fatal(1, "pll_wrap +pll_sys_period_ns must be 1.25 or 10, got %g", period_ns);
    period_ps = period_ns * 1000.0;
    osc_sys = 1'b0;
    if (!osc_bench) forever #(period_ps * 0.5) osc_sys = ~osc_sys;
  end

  // 200 MHz peripheral clock (5 ns = 5000 ps period, fixed).
  initial begin : gen_clk_periph
    osc_periph = 1'b0;
    if (!osc_bench) forever #2500ps osc_periph = ~osc_periph;
  end

  /////////////////////////////
  // ref -- straight through
  /////////////////////////////

  assign clk_ref_o = osc_ref;

  /////////////////////////////
  // sys -- mux chain
  /////////////////////////////

  logic clk_sys_mux2;
  logic clk_sys_muxed;

  prim_clock_mux2 u_sys_clk_mux2 (
    .clk0_i (osc_ref),
    .clk1_i (osc_sys),
    .sel_i  (1'b1),
    .clk_o  (clk_sys_mux2)
  );

  prim_ag_clk_mux #(
    .SelectOnReset (1'b0)
  ) u_sys_ag_mux (
    .clk0_i     (osc_ref),
    .clk1_i     (clk_sys_mux2),
    .rst_clk0_ni(rst_ni),
    .rst_clk1_ni(rst_ni),
    .test_en_i  (1'b0),
    .sel_i      (1'b1),
    .clk_o      (clk_sys_muxed)
  );

  assign clk_sys_o = osc_bench ? osc_sys : clk_sys_muxed;

  /////////////////////////////
  // periph -- mux chain
  /////////////////////////////

  logic clk_periph_mux2;
  logic clk_periph_muxed;

  prim_clock_mux2 u_periph_clk_mux2 (
    .clk0_i (osc_ref),
    .clk1_i (osc_periph),
    .sel_i  (1'b1),
    .clk_o  (clk_periph_mux2)
  );

  prim_ag_clk_mux #(
    .SelectOnReset (1'b0)
  ) u_periph_ag_mux (
    .clk0_i     (osc_ref),
    .clk1_i     (clk_periph_mux2),
    .rst_clk0_ni(rst_ni),
    .rst_clk1_ni(rst_ni),
    .test_en_i  (1'b0),
    .sel_i      (1'b1),
    .clk_o      (clk_periph_muxed)
  );

  assign clk_periph_o = osc_bench ? osc_periph : clk_periph_muxed;

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
