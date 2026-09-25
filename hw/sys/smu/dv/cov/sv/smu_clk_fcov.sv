// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU clock-domain functional coverage, from the SMU-CLK-DOMAINS scenarios
// of the feature list: the four primary-domain blocks clocked together, and
// the telemetry and SEP-watchdog domains running apart from them.
//
// The block clocks arrive as the hierarchical clock mirrors tb_wrapper_top
// exposes (obs_*_clk_o).
//
// A clock is measured by counting its rising edges and reading the counters
// half a clk_smu period later, on the falling edge of clk_smu. A block on
// clk_smu then advances by exactly the window length; a clock on another
// domain advances by some other amount. Sampling on the falling edge keeps
// the counters, which move on rising edges, out of the sampling cycle.
//
// SEP PRESENCE: the SEP, crossbar and SEP-watchdog measurements sit in the
// `g_sep` generate block, so a SEP=0 build carries no unhittable point and
// one coverage policy can grade both elaborations.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_clk_fcov #(
  // 0 on an elaboration without SEP. The SEP, crossbar and SEP-watchdog
  // clock and reset mirrors are tied off there, so the points that measure
  // them are dropped rather than carried unhittable.
  parameter bit SepPresent = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_primary_smc_clk_ni,

  // Primary-domain block clocks and resets, as the blocks see them.
  input wire smc_clk_i,
  input wire dtp_clk_i,
  input wire sep_clk_i,
  input wire xbar_clk_i,
  input wire smc_rst_ni,
  input wire dtp_rst_ni,
  input wire sep_rst_ni,
  input wire xbar_rst_ni,

  // The two domains the spec keeps apart from the primary one.
  input wire tel_clk_i,
  input wire sep_wdt_clk_i
);

  localparam int unsigned WindowLen = 16;
  localparam logic [3:0] WindowLast = 4'(WindowLen - 1);
  localparam logic [15:0] WindowEdges = 16'(WindowLen - 1);

  wire in_reset = (rst_primary_smc_clk_ni !== 1'b1);
  wire clk_smu_n = ~clk_smu_i;

  // ------------------------------------------------------------------
  // Rising-edge counters, one per measured clock; only their differences
  // are read.
  // ------------------------------------------------------------------
  logic [15:0] smc_cnt_q, dtp_cnt_q, tel_cnt_q;
  always_ff @(posedge smc_clk_i) begin
    if (in_reset) smc_cnt_q <= '0;
    else smc_cnt_q <= smc_cnt_q + 16'd1;
  end
  always_ff @(posedge dtp_clk_i) begin
    if (in_reset) dtp_cnt_q <= '0;
    else dtp_cnt_q <= dtp_cnt_q + 16'd1;
  end
  always_ff @(posedge tel_clk_i) begin
    if (in_reset) tel_cnt_q <= '0;
    else tel_cnt_q <= tel_cnt_q + 16'd1;
  end

  // ------------------------------------------------------------------
  // Measurement window on the falling edge of clk_smu.
  // ------------------------------------------------------------------
  logic [3:0] win_q;
  logic [15:0] smc_start_q, dtp_start_q, tel_start_q;
  always_ff @(posedge clk_smu_n) begin
    if (in_reset) begin
      win_q <= '0;
      smc_start_q <= '0;
      dtp_start_q <= '0;
      tel_start_q <= '0;
    end else begin
      win_q <= win_q + 4'd1;
      if (win_q == 4'd0) begin
        smc_start_q <= smc_cnt_q;
        dtp_start_q <= dtp_cnt_q;
        tel_start_q <= tel_cnt_q;
      end
    end
  end

  wire window_end = (win_q == WindowLast);
  wire window_start = (win_q == 4'd0);
  wire [15:0] smc_delta = smc_cnt_q - smc_start_q;
  wire [15:0] dtp_delta = dtp_cnt_q - dtp_start_q;
  wire [15:0] tel_delta = tel_cnt_q - tel_start_q;

  wire telemetry_domain_independent_e =
      window_end && (tel_delta !== 16'd0) && (tel_delta !== WindowEdges);
  `OCAH_FCOV_COVER(c_telemetry_domain_independent, telemetry_domain_independent_e, clk_smu_n,
                   in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the per-window edge count of the
  // telemetry domain against the primary one, as a relation. The bench keeps
  // the telemetry period unequal to the primary one so the two domains stay
  // distinguishable at the boundary, and the SEP watchdog clock runs an order
  // of magnitude slower, so `slower` and `faster` are the cells the bench
  // walks; `same_rate` and `stopped` name the relations it does not.
  // ------------------------------------------------------------------
  covergroup cg_tel_rate with function sample (logic [15:0] tel);
    option.per_instance = 1;
    // An equal-rate clock counts WindowEdges or WindowEdges + 1 edges in the
    // window depending on phase, so same_rate is not a stable bin; the bench
    // never gates the telemetry clock.
    cp_tel: coverpoint tel {
      bins stopped = {16'd0};
      bins slower = {[16'd1 : WindowEdges - 16'd1]};
      bins same_rate = {WindowEdges};
      bins faster = {[WindowEdges + 16'd1 : 16'hFFFF]};
      ignore_bins never_gated = {16'd0};
      ignore_bins phase_dependent = {WindowEdges};
    }
  endgroup

  cg_tel_rate u_cg_tel_rate = new();

  always_ff @(posedge clk_smu_n) begin
    if (!in_reset && window_end) u_cg_tel_rate.sample(tel_delta);
  end
`endif

  // ------------------------------------------------------------------
  // The SEP and crossbar blocks sharing the primary domain, and the
  // SEP watchdog domain running while SEP is out of reset. Only
  // elaborated with SEP present: both blocks and the watchdog clock come
  // out of smu.sv's gen_sep branch, and the bench ties their clock and
  // reset mirrors off without it.
  // ------------------------------------------------------------------
  if (SepPresent) begin : g_sep
    logic [15:0] sep_cnt_q, xbar_cnt_q, wdt_cnt_q;
    always_ff @(posedge sep_clk_i) begin
      if (in_reset) sep_cnt_q <= '0;
      else sep_cnt_q <= sep_cnt_q + 16'd1;
    end
    always_ff @(posedge xbar_clk_i) begin
      if (in_reset) xbar_cnt_q <= '0;
      else xbar_cnt_q <= xbar_cnt_q + 16'd1;
    end
    always_ff @(posedge sep_wdt_clk_i) begin
      if (in_reset) wdt_cnt_q <= '0;
      else wdt_cnt_q <= wdt_cnt_q + 16'd1;
    end

    logic [15:0] sep_start_q, xbar_start_q, wdt_start_q;
    always_ff @(posedge clk_smu_n) begin
      if (in_reset) begin
        sep_start_q <= '0;
        xbar_start_q <= '0;
        wdt_start_q <= '0;
      end else if (window_start) begin
        sep_start_q <= sep_cnt_q;
        xbar_start_q <= xbar_cnt_q;
        wdt_start_q <= wdt_cnt_q;
      end
    end

    wire [15:0] sep_delta = sep_cnt_q - sep_start_q;
    wire [15:0] xbar_delta = xbar_cnt_q - xbar_start_q;
    wire [15:0] wdt_delta = wdt_cnt_q - wdt_start_q;

    wire blocks_out_of_reset = (smc_rst_ni === 1'b1) && (dtp_rst_ni === 1'b1)
        && (sep_rst_ni === 1'b1) && (xbar_rst_ni === 1'b1);
    wire blocks_on_clk_smu = (smc_delta === WindowEdges) && (dtp_delta === WindowEdges)
        && (sep_delta === WindowEdges) && (xbar_delta === WindowEdges);
    wire primary_domain_hosts_all_four_blocks_e =
        window_end && blocks_out_of_reset && blocks_on_clk_smu;
    wire sep_wdt_domain_active_e = window_end && (wdt_delta !== 16'd0) && (sep_rst_ni === 1'b1);
    `OCAH_FCOV_COVER(c_primary_domain_hosts_all_four_blocks, primary_domain_hosts_all_four_blocks_e,
                     clk_smu_n, in_reset)
    `OCAH_FCOV_COVER(c_sep_wdt_domain_active, sep_wdt_domain_active_e, clk_smu_n, in_reset)

`ifndef VERILATOR
    // Commercial-simulator covergroup: the SEP watchdog per-window edge
    // count against the primary domain.
    covergroup cg_wdt_rate with function sample (logic [15:0] wdt);
      option.per_instance = 1;
      // The SEP watchdog clock is an order of magnitude slower than the SMU
      // clock (80/100/120 ns against 8/10/12 ns) and the bench never gates it.
      cp_wdt: coverpoint wdt {
        bins stopped = {16'd0};
        bins slower = {[16'd1 : WindowEdges - 16'd1]};
        bins same_rate = {WindowEdges};
        bins faster = {[WindowEdges + 16'd1 : 16'hFFFF]};
        ignore_bins never_gated = {16'd0};
        ignore_bins not_reached = {[WindowEdges : 16'hFFFF]};
      }
    endgroup

    cg_wdt_rate u_cg_wdt_rate = new();

    always_ff @(posedge clk_smu_n) begin
      if (!in_reset && window_end) u_cg_wdt_rate.sample(wdt_delta);
    end
`endif
  end

endmodule : smu_clk_fcov
