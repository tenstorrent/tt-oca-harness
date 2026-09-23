// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU address-map and inbound-fabric functional coverage: the
// `xbar_route_cg` filter intent and the `reg_access_cg` outcome intent of
// smu_fcov.py as native cover-property points.
//
// Those two live in smu_fcov.py as a static test-name-to-bin table: running
// a named test asserts that its listed bins were hit, without observing a
// signal. The points here are driven by the map outputs and the inbound AXI
// handshake, so a bin is hit because the DUT did the thing.
//
// One passive, signal-driven module. Every port is a signal of the bench
// top, except axil_external_active_i, which the bench reads from a window
// smu_wrapper keeps inside itself.
//
// Points must need stimulus beyond power-up and reset release. The map
// outputs take whatever the fuses and straps leave at power-up, so a level
// on them proves nothing; each is qualified by the value having changed,
// which is what programming the window looks like from outside.
//
// SEP PRESENCE: the SEP-aperture points sit in the `g_sep` generate block, so
// a SEP=0 build carries no unhittable point and one coverage policy can grade
// both elaborations.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch -- without one a four-state simulator holds it at X
// and the points that read it are unhittable on the commercial path.

`include "ocah_fcov_macros.svh"

module smu_xbar_fcov #(
  // 0 on an elaboration without SEP. The SEP aperture outputs come from the
  // SEP CSR block, so smu.sv's gen_no_sep branch ties base and size to '0
  // and they can never move; the points that watch them move are dropped
  // rather than carried unhittable.
  parameter bit SepPresent = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_cold_ni,

  // Programmed address windows broadcast to the subsystems.
  input wire [55:0] sep_global_base_i,
  input wire [55:0] sep_region_size_i,
  input wire [55:0] smc_global_base_i,
  input wire [31:0] smc_region_size_i,

  // Inbound AXI manager into the crossbar.
  input wire s_axi_awvalid_i,
  input wire s_axi_awready_i,
  input wire s_axi_wvalid_i,
  input wire s_axi_wready_i,
  input wire s_axi_wlast_i,
  input wire s_axi_bvalid_i,
  input wire s_axi_bready_i,
  input wire [1:0] s_axi_bresp_i,
  input wire s_axi_arvalid_i,
  input wire s_axi_arready_i,
  input wire s_axi_rvalid_i,
  input wire s_axi_rready_i,
  input wire s_axi_rlast_i,
  input wire [1:0] s_axi_rresp_i,

  // Crossbar traffic counters, inbound and outbound.
  input wire [31:0] axi_in_awvalid_count_i,
  input wire [31:0] axi_out_awvalid_count_i,

  // Downstream AXI-Lite activity.
  input wire axil_external_active_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Address-window programming. A window is "programmed" when its value
  // moves; reprogramming is a second move, which is the shrink/regrow
  // case the filter tests drive.
  // ------------------------------------------------------------------
  logic [55:0] smc_base_q;
  logic [31:0] smc_size_q;
  logic smc_base_prog_q, smc_size_prog_q, smc_size_reprog_q;

  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      smc_base_q <= smc_global_base_i;
      smc_size_q <= smc_region_size_i;
      smc_base_prog_q <= 1'b0;
      smc_size_prog_q <= 1'b0;
      smc_size_reprog_q <= 1'b0;
    end else begin
      smc_base_q <= smc_global_base_i;
      smc_size_q <= smc_region_size_i;
      if (smc_global_base_i !== smc_base_q) smc_base_prog_q <= 1'b1;
      if (smc_region_size_i !== smc_size_q) begin
        smc_size_prog_q <= 1'b1;
        if (smc_size_prog_q) smc_size_reprog_q <= 1'b1;
      end
    end
  end

  wire smc_base_programmed_e = smc_base_prog_q;
  wire smc_size_programmed_e = smc_size_prog_q;
  wire smc_size_reprogrammed_e = smc_size_reprog_q;
  `OCAH_FCOV_COVER(c_map_smc_base_programmed, smc_base_programmed_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_map_smc_size_programmed, smc_size_programmed_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_map_smc_size_reprogrammed, smc_size_reprogrammed_e, clk_smu_i, in_reset)

  // A zero-size window denies the whole region; it is a legal programmed
  // state the filter tests use and is worth naming separately.
  wire smc_size_zero_e = smc_size_prog_q && (smc_region_size_i === '0);
  `OCAH_FCOV_COVER(c_map_smc_size_zero, smc_size_zero_e, clk_smu_i, in_reset)

  // The SEP aperture, watched the same way. Only elaborated with SEP
  // present: base and size are tied to '0 without it and never move.
  if (SepPresent) begin : g_sep
    logic [55:0] sep_base_q, sep_size_q;
    logic sep_base_prog_q, sep_size_prog_q, sep_size_reprog_q;

    always_ff @(posedge clk_smu_i) begin
      if (in_reset) begin
        sep_base_q <= sep_global_base_i;
        sep_size_q <= sep_region_size_i;
        sep_base_prog_q <= 1'b0;
        sep_size_prog_q <= 1'b0;
        sep_size_reprog_q <= 1'b0;
      end else begin
        sep_base_q <= sep_global_base_i;
        sep_size_q <= sep_region_size_i;
        if (sep_global_base_i !== sep_base_q) sep_base_prog_q <= 1'b1;
        if (sep_region_size_i !== sep_size_q) begin
          sep_size_prog_q <= 1'b1;
          if (sep_size_prog_q) sep_size_reprog_q <= 1'b1;
        end
      end
    end

    wire sep_base_programmed_e = sep_base_prog_q;
    wire sep_size_programmed_e = sep_size_prog_q;
    wire sep_size_reprogrammed_e = sep_size_reprog_q;
    wire sep_size_zero_e = sep_size_prog_q && (sep_region_size_i === '0);
    `OCAH_FCOV_COVER(c_map_sep_base_programmed, sep_base_programmed_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_map_sep_size_programmed, sep_size_programmed_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_map_sep_size_reprogrammed, sep_size_reprogrammed_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_map_sep_size_zero, sep_size_zero_e, clk_smu_i, in_reset)

`ifndef VERILATOR
    // Commercial-simulator covergroup: the programmed and zero-size states
    // of the SEP window, which a flat point list cannot cross.
    covergroup cg_sep_window with function sample (logic prog, logic zero);
      option.per_instance = 1;
      cp_prog: coverpoint prog;
      cp_zero: coverpoint zero;
      x_programmed: cross cp_prog, cp_zero;
    endgroup

    cg_sep_window u_cg_sep_window = new();

    always_ff @(posedge clk_smu_i) begin
      if (!in_reset) u_cg_sep_window.sample(sep_size_prog_q, sep_size_zero_e);
    end
`endif
  end

  // ------------------------------------------------------------------
  // Inbound AXI handshake and response codes. All four response
  // encodings get a point, so an encoding the suite never produces is a
  // named hole rather than absent from the model.
  // ------------------------------------------------------------------
  wire aw_accept_e = (s_axi_awvalid_i === 1'b1) && (s_axi_awready_i === 1'b1);
  wire aw_stall_e = (s_axi_awvalid_i === 1'b1) && (s_axi_awready_i === 1'b0);
  wire w_last_e = (s_axi_wvalid_i === 1'b1) && (s_axi_wready_i === 1'b1)
      && (s_axi_wlast_i === 1'b1);
  wire ar_accept_e = (s_axi_arvalid_i === 1'b1) && (s_axi_arready_i === 1'b1);
  wire ar_stall_e = (s_axi_arvalid_i === 1'b1) && (s_axi_arready_i === 1'b0);
  wire r_last_e = (s_axi_rvalid_i === 1'b1) && (s_axi_rready_i === 1'b1)
      && (s_axi_rlast_i === 1'b1);
  `OCAH_FCOV_COVER(c_axi_in_aw_accept, aw_accept_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_aw_stall, aw_stall_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_w_last, w_last_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_ar_accept, ar_accept_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_ar_stall, ar_stall_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_r_last, r_last_e, clk_smu_i, in_reset)

  wire b_accept = (s_axi_bvalid_i === 1'b1) && (s_axi_bready_i === 1'b1);
  wire r_accept = (s_axi_rvalid_i === 1'b1) && (s_axi_rready_i === 1'b1);
  wire bresp_okay_e = b_accept && (s_axi_bresp_i == 2'b00);
  wire bresp_exokay_e = b_accept && (s_axi_bresp_i == 2'b01);
  wire bresp_slverr_e = b_accept && (s_axi_bresp_i == 2'b10);
  wire bresp_decerr_e = b_accept && (s_axi_bresp_i == 2'b11);
  wire rresp_okay_e = r_accept && (s_axi_rresp_i == 2'b00);
  wire rresp_exokay_e = r_accept && (s_axi_rresp_i == 2'b01);
  wire rresp_slverr_e = r_accept && (s_axi_rresp_i == 2'b10);
  wire rresp_decerr_e = r_accept && (s_axi_rresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_axi_in_bresp_okay, bresp_okay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_bresp_exokay, bresp_exokay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_bresp_slverr, bresp_slverr_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_bresp_decerr, bresp_decerr_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_okay, rresp_okay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_exokay, rresp_exokay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_slverr, rresp_slverr_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_decerr, rresp_decerr_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // Routing outcome. An inbound write that advances the inbound counter
  // without advancing the outbound one was answered inside SMU rather
  // than forwarded -- which is what a denied window looks like from the
  // crossbar's edge, and the observation `outside_still_decerr` needs.
  // ------------------------------------------------------------------
  logic [31:0] in_count_q, out_count_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      in_count_q <= '0;
      out_count_q <= '0;
    end else begin
      in_count_q <= axi_in_awvalid_count_i;
      out_count_q <= axi_out_awvalid_count_i;
    end
  end

  wire in_advanced = (axi_in_awvalid_count_i !== in_count_q);
  wire out_advanced = (axi_out_awvalid_count_i !== out_count_q);
  wire route_not_forwarded_e = in_advanced && !out_advanced;
  wire axil_external_e = (axil_external_active_i === 1'b1);
  `OCAH_FCOV_COVER(c_route_inbound_not_forwarded, route_not_forwarded_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_external_active, axil_external_e, clk_smu_i, in_reset)

  // An inbound write answered with no outbound AW having fired since its own
  // AW was accepted: ext_in reached its target without a route to ext_out.
  logic out_since_in_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      out_since_in_q <= 1'b0;
    end else begin
      if (aw_accept_e) out_since_in_q <= 1'b0;
      else if (out_advanced) out_since_in_q <= 1'b1;
    end
  end

  wire no_route_ext_in_to_ext_out_e = b_accept && (out_since_in_q === 1'b0);
  `OCAH_FCOV_COVER(c_no_route_ext_in_to_ext_out, no_route_ext_in_to_ext_out_e, clk_smu_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the response-code distribution and
  // the programmed-window cross a flat point list cannot express.
  // ------------------------------------------------------------------
  covergroup cg_axi_in_resp with function sample (logic [1:0] resp);
    option.per_instance = 1;
    cp_resp: coverpoint resp {
      bins okay = {2'b00}; bins exokay = {2'b01}; bins slverr = {2'b10}; bins decerr = {2'b11};
    }
  endgroup

  covergroup cg_map_window with function sample (logic prog, logic zero);
    option.per_instance = 1;
    cp_prog: coverpoint prog;
    cp_zero: coverpoint zero;
    x_programmed: cross cp_prog, cp_zero;
  endgroup

  cg_axi_in_resp u_cg_bresp = new();
  cg_axi_in_resp u_cg_rresp = new();
  cg_map_window u_cg_smc_window = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset) begin
      if (b_accept) u_cg_bresp.sample(s_axi_bresp_i);
      if (r_accept) u_cg_rresp.sample(s_axi_rresp_i);
      u_cg_smc_window.sample(smc_size_prog_q, smc_size_zero_e);
    end
  end
`endif

endmodule : smu_xbar_fcov
