// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU address-map and inbound-fabric functional coverage: the
// `xbar_route_cg` filter intent and the `reg_access_cg` outcome intent of
// smu_fcov.py as native cover-property points, driven by the map outputs and
// the inbound AXI handshake, and the routing, outstanding-depth and ID-order
// families of the six crossbar ports.
//
// One passive, signal-driven module. Every port is a signal of the bench
// top, except axil_external_active_i, which the bench reads from a window
// smu_wrapper keeps inside itself, and the xbar_* ports, which it reads at
// the ports of the crossbar instance.
//
// Points must need stimulus beyond power-up and reset release. The map
// outputs take whatever the fuses and straps leave at power-up, so a level
// on them proves nothing; each is qualified by the value having changed,
// which is what programming the window looks like from outside.
//
// SEP PRESENCE: the SEP-aperture points and the crossbar-port points sit in
// the `g_sep` generate block, so a SEP=0 build carries no unhittable point
// and one coverage policy can grade both elaborations.
//
// RESETS: the window-programming state follows the cold reset. The
// crossbar-port trackers and points follow the cold reset and the primary
// SMC-clock reset, which resets the crossbar and can fall while the cold
// reset stays high.
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
  // and they can never move, and smu.sv elaborates the crossbar only with
  // SEP; the points that watch either are dropped rather than carried
  // unhittable.
  parameter bit SEP_PRESENT = 1'b1  // Set when the SEP and the crossbar are elaborated.
) (
  input wire clk_smu_i,  // SMU fabric clock that samples every point.
  input wire rst_cold_ni,  // Cold reset, active low; every point is disabled while it is low.
  input wire rst_primary_smc_clk_ni,  // Crossbar reset, active low; clears the port trackers.
  input wire [55:0] sep_global_base_i,  // SEP aperture base broadcast to the subsystems.
  input wire [55:0] sep_region_size_i,  // SEP aperture size in bytes; zero disables it.
  input wire [55:0] smc_global_base_i,  // SMC aperture base broadcast to the subsystems.
  input wire [31:0] smc_region_size_i,  // SMC aperture size in bytes; zero disables it.
  input wire s_axi_awvalid_i,  // Inbound AXI manager AW valid at the wrapper boundary.
  input wire s_axi_awready_i,  // Inbound AXI AW ready at the wrapper boundary.
  input wire s_axi_wvalid_i,  // Inbound AXI W valid at the wrapper boundary.
  input wire s_axi_wready_i,  // Inbound AXI W ready at the wrapper boundary.
  input wire s_axi_wlast_i,  // Inbound AXI WLAST at the wrapper boundary.
  input wire s_axi_bvalid_i,  // Inbound AXI B valid at the wrapper boundary.
  input wire s_axi_bready_i,  // Inbound AXI B ready at the wrapper boundary.
  input wire [1:0] s_axi_bresp_i,  // Inbound AXI BRESP at the wrapper boundary.
  input wire s_axi_arvalid_i,  // Inbound AXI AR valid at the wrapper boundary.
  input wire s_axi_arready_i,  // Inbound AXI AR ready at the wrapper boundary.
  input wire s_axi_rvalid_i,  // Inbound AXI R valid at the wrapper boundary.
  input wire s_axi_rready_i,  // Inbound AXI R ready at the wrapper boundary.
  input wire s_axi_rlast_i,  // Inbound AXI RLAST at the wrapper boundary.
  input wire [1:0] s_axi_rresp_i,  // Inbound AXI RRESP at the wrapper boundary.
  input wire [31:0] axi_in_awvalid_count_i,  // Crossbar inbound AW valid count.
  input wire [31:0] axi_out_awvalid_count_i,  // Crossbar outbound AW valid count.
  input wire axil_external_active_i,  // Downstream AXI-Lite window activity.
  input wire xbar_sep_out_awvalid_i,  // sep_out AW valid into the crossbar.
  input wire xbar_sep_out_awready_i,  // sep_out AW ready from the crossbar.
  input wire [55:0] xbar_sep_out_awaddr_i,  // sep_out AW address, decoded against the apertures.
  input wire [7:0] xbar_sep_out_awid_i,  // sep_out AW ID as the initiator issues it.
  input wire xbar_sep_out_arvalid_i,  // sep_out AR valid into the crossbar.
  input wire xbar_sep_out_arready_i,  // sep_out AR ready from the crossbar.
  input wire [55:0] xbar_sep_out_araddr_i,  // sep_out AR address, decoded against the apertures.
  input wire [7:0] xbar_sep_out_arid_i,  // sep_out AR ID as the initiator issues it.
  input wire xbar_sep_out_bvalid_i,  // sep_out B valid from the crossbar.
  input wire xbar_sep_out_bready_i,  // sep_out B ready from the initiator.
  input wire [7:0] xbar_sep_out_bid_i,  // sep_out B ID returned to the initiator.
  input wire [1:0] xbar_sep_out_bresp_i,  // sep_out BRESP returned to the initiator.
  input wire xbar_sep_out_rvalid_i,  // sep_out R valid from the crossbar.
  input wire xbar_sep_out_rready_i,  // sep_out R ready from the initiator.
  input wire xbar_sep_out_rlast_i,  // sep_out RLAST returned to the initiator.
  input wire [7:0] xbar_sep_out_rid_i,  // sep_out R ID returned to the initiator.
  input wire [1:0] xbar_sep_out_rresp_i,  // sep_out RRESP returned to the initiator.
  input wire xbar_smc_out_awvalid_i,  // smc_out AW valid into the crossbar.
  input wire xbar_smc_out_awready_i,  // smc_out AW ready from the crossbar.
  input wire [55:0] xbar_smc_out_awaddr_i,  // smc_out AW address, decoded against the apertures.
  input wire [7:0] xbar_smc_out_awid_i,  // smc_out AW ID as the initiator issues it.
  input wire xbar_smc_out_arvalid_i,  // smc_out AR valid into the crossbar.
  input wire xbar_smc_out_arready_i,  // smc_out AR ready from the crossbar.
  input wire [55:0] xbar_smc_out_araddr_i,  // smc_out AR address, decoded against the apertures.
  input wire [7:0] xbar_smc_out_arid_i,  // smc_out AR ID as the initiator issues it.
  input wire xbar_smc_out_bvalid_i,  // smc_out B valid from the crossbar.
  input wire xbar_smc_out_bready_i,  // smc_out B ready from the initiator.
  input wire [7:0] xbar_smc_out_bid_i,  // smc_out B ID returned to the initiator.
  input wire [1:0] xbar_smc_out_bresp_i,  // smc_out BRESP returned to the initiator.
  input wire xbar_smc_out_rvalid_i,  // smc_out R valid from the crossbar.
  input wire xbar_smc_out_rready_i,  // smc_out R ready from the initiator.
  input wire xbar_smc_out_rlast_i,  // smc_out RLAST returned to the initiator.
  input wire [7:0] xbar_smc_out_rid_i,  // smc_out R ID returned to the initiator.
  input wire [1:0] xbar_smc_out_rresp_i,  // smc_out RRESP returned to the initiator.
  input wire xbar_ext_in_awvalid_i,  // ext_in AW valid into the crossbar.
  input wire xbar_ext_in_awready_i,  // ext_in AW ready from the crossbar.
  input wire [55:0] xbar_ext_in_awaddr_i,  // ext_in AW address, decoded against the apertures.
  input wire [7:0] xbar_ext_in_awid_i,  // ext_in AW ID as the initiator issues it.
  input wire xbar_ext_in_arvalid_i,  // ext_in AR valid into the crossbar.
  input wire xbar_ext_in_arready_i,  // ext_in AR ready from the crossbar.
  input wire [55:0] xbar_ext_in_araddr_i,  // ext_in AR address, decoded against the apertures.
  input wire [7:0] xbar_ext_in_arid_i,  // ext_in AR ID as the initiator issues it.
  input wire xbar_ext_in_bvalid_i,  // ext_in B valid from the crossbar.
  input wire xbar_ext_in_bready_i,  // ext_in B ready from the initiator.
  input wire [7:0] xbar_ext_in_bid_i,  // ext_in B ID returned to the initiator.
  input wire [1:0] xbar_ext_in_bresp_i,  // ext_in BRESP returned to the initiator.
  input wire xbar_ext_in_rvalid_i,  // ext_in R valid from the crossbar.
  input wire xbar_ext_in_rready_i,  // ext_in R ready from the initiator.
  input wire xbar_ext_in_rlast_i,  // ext_in RLAST returned to the initiator.
  input wire [7:0] xbar_ext_in_rid_i,  // ext_in R ID returned to the initiator.
  input wire [1:0] xbar_ext_in_rresp_i,  // ext_in RRESP returned to the initiator.
  input wire xbar_sep_in_awvalid_i,  // sep_in AW valid toward the target.
  input wire xbar_sep_in_awready_i,  // sep_in AW ready from the target.
  input wire [9:0] xbar_sep_in_awid_i,  // sep_in AW ID carrying the crossbar port prefix.
  input wire xbar_sep_in_arvalid_i,  // sep_in AR valid toward the target.
  input wire xbar_sep_in_arready_i,  // sep_in AR ready from the target.
  input wire [9:0] xbar_sep_in_arid_i,  // sep_in AR ID carrying the crossbar port prefix.
  input wire xbar_sep_in_bvalid_i,  // sep_in B valid from the target.
  input wire xbar_sep_in_bready_i,  // sep_in B ready from the crossbar.
  input wire [9:0] xbar_sep_in_bid_i,  // sep_in B ID from the target.
  input wire xbar_sep_in_rvalid_i,  // sep_in R valid from the target.
  input wire xbar_sep_in_rready_i,  // sep_in R ready from the crossbar.
  input wire xbar_sep_in_rlast_i,  // sep_in RLAST from the target.
  input wire [9:0] xbar_sep_in_rid_i,  // sep_in R ID from the target.
  input wire xbar_smc_in_awvalid_i,  // smc_in AW valid toward the target.
  input wire xbar_smc_in_awready_i,  // smc_in AW ready from the target.
  input wire [9:0] xbar_smc_in_awid_i,  // smc_in AW ID carrying the crossbar port prefix.
  input wire xbar_smc_in_arvalid_i,  // smc_in AR valid toward the target.
  input wire xbar_smc_in_arready_i,  // smc_in AR ready from the target.
  input wire [9:0] xbar_smc_in_arid_i,  // smc_in AR ID carrying the crossbar port prefix.
  input wire xbar_smc_in_bvalid_i,  // smc_in B valid from the target.
  input wire xbar_smc_in_bready_i,  // smc_in B ready from the crossbar.
  input wire [9:0] xbar_smc_in_bid_i,  // smc_in B ID from the target.
  input wire xbar_smc_in_rvalid_i,  // smc_in R valid from the target.
  input wire xbar_smc_in_rready_i,  // smc_in R ready from the crossbar.
  input wire xbar_smc_in_rlast_i,  // smc_in RLAST from the target.
  input wire [9:0] xbar_smc_in_rid_i,  // smc_in R ID from the target.
  input wire xbar_ext_out_awvalid_i,  // ext_out AW valid toward the target.
  input wire xbar_ext_out_awready_i,  // ext_out AW ready from the target.
  input wire [9:0] xbar_ext_out_awid_i,  // ext_out AW ID carrying the crossbar port prefix.
  input wire xbar_ext_out_arvalid_i,  // ext_out AR valid toward the target.
  input wire xbar_ext_out_arready_i,  // ext_out AR ready from the target.
  input wire [9:0] xbar_ext_out_arid_i,  // ext_out AR ID carrying the crossbar port prefix.
  input wire xbar_ext_out_bvalid_i,  // ext_out B valid from the target.
  input wire xbar_ext_out_bready_i,  // ext_out B ready from the crossbar.
  input wire [9:0] xbar_ext_out_bid_i,  // ext_out B ID from the target.
  input wire xbar_ext_out_rvalid_i,  // ext_out R valid from the target.
  input wire xbar_ext_out_rready_i,  // ext_out R ready from the crossbar.
  input wire xbar_ext_out_rlast_i,  // ext_out RLAST from the target.
  input wire [9:0] xbar_ext_out_rid_i  // ext_out R ID from the target.
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

  // smc_base_config REGION_SIZE must be a non-zero power of two, so a zero
  // SMC window is an illegal programming. Phase 2 (SMU_FCOV.adoc).
  wire smc_size_zero_e = smc_size_prog_q && (smc_region_size_i === '0);
`ifdef SMU_FCOV_PHASE2
  `OCAH_FCOV_COVER(c_map_smc_size_zero, smc_size_zero_e, clk_smu_i, in_reset)
`endif

  // The SEP aperture, watched the same way. Only elaborated with SEP
  // present: base and size are tied to '0 without it and never move.
  if (SEP_PRESENT) begin : g_sep
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

    // Covergroup: the states the SEP window passes through. A zero size is
    // only recorded once the size has been programmed, so an unprogrammed
    // zero-size state does not exist.
    covergroup cg_sep_window with function sample (logic [1:0] prog_zero);
      option.per_instance = 1;
      cp_state: coverpoint prog_zero {
        bins unprogrammed = {2'b00}; bins programmed = {2'b10}; bins programmed_zero = {2'b11};
      }
    endgroup

    cg_sep_window u_cg_sep_window = new();

    always_ff @(posedge clk_smu_i) begin
      if (!in_reset) u_cg_sep_window.sample({sep_size_prog_q, sep_size_zero_e});
    end

    // ----------------------------------------------------------------
    // Crossbar ports. Bit or element p of every per-port vector is, in
    // order, sep_out, smc_out, ext_in (the initiators) and sep_in,
    // smc_in, ext_out (the targets); lane l = 2p + d is port p, writes
    // for d = 0 and reads for d = 1. Every point below is sampled on a
    // handshake and is a stimulus criterion: none compares a response
    // with an expected value.
    // ----------------------------------------------------------------
    localparam int unsigned NumPorts = 6;
    localparam int unsigned NumLanes = 2 * NumPorts;
    localparam int unsigned NumRouteLanes = 6;
    localparam int unsigned IdSlots = 8;
    localparam int unsigned XbarIdW = 10;

    wire xbar_in_reset = in_reset || (rst_primary_smc_clk_ni !== 1'b1);

    logic [NumPorts-1:0] aw_hs;
    logic [NumPorts-1:0] ar_hs;
    logic [NumPorts-1:0] b_hs;
    logic [NumPorts-1:0] rl_hs;
    assign aw_hs[0] = (xbar_sep_out_awvalid_i === 1'b1) && (xbar_sep_out_awready_i === 1'b1);
    assign ar_hs[0] = (xbar_sep_out_arvalid_i === 1'b1) && (xbar_sep_out_arready_i === 1'b1);
    assign b_hs[0] = (xbar_sep_out_bvalid_i === 1'b1) && (xbar_sep_out_bready_i === 1'b1);
    assign rl_hs[0] = (xbar_sep_out_rvalid_i === 1'b1) && (xbar_sep_out_rready_i === 1'b1)
        && (xbar_sep_out_rlast_i === 1'b1);
    assign aw_hs[1] = (xbar_smc_out_awvalid_i === 1'b1) && (xbar_smc_out_awready_i === 1'b1);
    assign ar_hs[1] = (xbar_smc_out_arvalid_i === 1'b1) && (xbar_smc_out_arready_i === 1'b1);
    assign b_hs[1] = (xbar_smc_out_bvalid_i === 1'b1) && (xbar_smc_out_bready_i === 1'b1);
    assign rl_hs[1] = (xbar_smc_out_rvalid_i === 1'b1) && (xbar_smc_out_rready_i === 1'b1)
        && (xbar_smc_out_rlast_i === 1'b1);
    assign aw_hs[2] = (xbar_ext_in_awvalid_i === 1'b1) && (xbar_ext_in_awready_i === 1'b1);
    assign ar_hs[2] = (xbar_ext_in_arvalid_i === 1'b1) && (xbar_ext_in_arready_i === 1'b1);
    assign b_hs[2] = (xbar_ext_in_bvalid_i === 1'b1) && (xbar_ext_in_bready_i === 1'b1);
    assign rl_hs[2] = (xbar_ext_in_rvalid_i === 1'b1) && (xbar_ext_in_rready_i === 1'b1)
        && (xbar_ext_in_rlast_i === 1'b1);
    assign aw_hs[3] = (xbar_sep_in_awvalid_i === 1'b1) && (xbar_sep_in_awready_i === 1'b1);
    assign ar_hs[3] = (xbar_sep_in_arvalid_i === 1'b1) && (xbar_sep_in_arready_i === 1'b1);
    assign b_hs[3] = (xbar_sep_in_bvalid_i === 1'b1) && (xbar_sep_in_bready_i === 1'b1);
    assign rl_hs[3] = (xbar_sep_in_rvalid_i === 1'b1) && (xbar_sep_in_rready_i === 1'b1)
        && (xbar_sep_in_rlast_i === 1'b1);
    assign aw_hs[4] = (xbar_smc_in_awvalid_i === 1'b1) && (xbar_smc_in_awready_i === 1'b1);
    assign ar_hs[4] = (xbar_smc_in_arvalid_i === 1'b1) && (xbar_smc_in_arready_i === 1'b1);
    assign b_hs[4] = (xbar_smc_in_bvalid_i === 1'b1) && (xbar_smc_in_bready_i === 1'b1);
    assign rl_hs[4] = (xbar_smc_in_rvalid_i === 1'b1) && (xbar_smc_in_rready_i === 1'b1)
        && (xbar_smc_in_rlast_i === 1'b1);
    assign aw_hs[5] = (xbar_ext_out_awvalid_i === 1'b1) && (xbar_ext_out_awready_i === 1'b1);
    assign ar_hs[5] = (xbar_ext_out_arvalid_i === 1'b1) && (xbar_ext_out_arready_i === 1'b1);
    assign b_hs[5] = (xbar_ext_out_bvalid_i === 1'b1) && (xbar_ext_out_bready_i === 1'b1);
    assign rl_hs[5] = (xbar_ext_out_rvalid_i === 1'b1) && (xbar_ext_out_rready_i === 1'b1)
        && (xbar_ext_out_rlast_i === 1'b1);

    // Initiator IDs are zero-extended to the target ID width.
    wire [NumPorts-1:0][XbarIdW-1:0] aw_id = {
      xbar_ext_out_awid_i,
      xbar_smc_in_awid_i,
      xbar_sep_in_awid_i,
      XbarIdW'(xbar_ext_in_awid_i),
      XbarIdW'(xbar_smc_out_awid_i),
      XbarIdW'(xbar_sep_out_awid_i)
    };
    wire [NumPorts-1:0][XbarIdW-1:0] ar_id = {
      xbar_ext_out_arid_i,
      xbar_smc_in_arid_i,
      xbar_sep_in_arid_i,
      XbarIdW'(xbar_ext_in_arid_i),
      XbarIdW'(xbar_smc_out_arid_i),
      XbarIdW'(xbar_sep_out_arid_i)
    };
    wire [NumPorts-1:0][XbarIdW-1:0] b_id = {
      xbar_ext_out_bid_i,
      xbar_smc_in_bid_i,
      xbar_sep_in_bid_i,
      XbarIdW'(xbar_ext_in_bid_i),
      XbarIdW'(xbar_smc_out_bid_i),
      XbarIdW'(xbar_sep_out_bid_i)
    };
    wire [NumPorts-1:0][XbarIdW-1:0] r_id = {
      xbar_ext_out_rid_i,
      xbar_smc_in_rid_i,
      xbar_sep_in_rid_i,
      XbarIdW'(xbar_ext_in_rid_i),
      XbarIdW'(xbar_smc_out_rid_i),
      XbarIdW'(xbar_sep_out_rid_i)
    };
    wire [2:0][55:0] init_awaddr = {
      xbar_ext_in_awaddr_i, xbar_smc_out_awaddr_i, xbar_sep_out_awaddr_i
    };
    wire [2:0][55:0] init_araddr = {
      xbar_ext_in_araddr_i, xbar_smc_out_araddr_i, xbar_sep_out_araddr_i
    };
    wire [2:0][1:0] init_bresp = {xbar_ext_in_bresp_i, xbar_smc_out_bresp_i, xbar_sep_out_bresp_i};
    wire [2:0][1:0] init_rresp = {xbar_ext_in_rresp_i, xbar_smc_out_rresp_i, xbar_sep_out_rresp_i};

    logic [NumLanes-1:0] push_v;
    logic [NumLanes-1:0] idle_v;
    logic [NumLanes-1:0] depth_1_v;
    logic [NumLanes-1:0] depth_2_4_v;
    logic [NumLanes-1:0] depth_5_8_v;
    logic [NumLanes-1:0] depth_gt8_v;
    logic [NumLanes-1:0] id_inorder_v;
    logic [NumLanes-1:0] id_ooo_v;
    logic [NumLanes-1:0][15:0] depth_v;

    // Outstanding depth and ID return order, one tracker per lane. The
    // depth is the address phases accepted minus the B or RLAST beats
    // accepted before this cycle, plus the address phase being accepted.
    // The open-ID list holds the IDs in acceptance order; a response whose
    // ID first matches an entry other than the oldest returns out of
    // order, and one that matches the oldest while an entry with another
    // ID is open returns in order. With one distinct ID open nothing is
    // sampled. An address phase that finds the list full marks it lost, and
    // the lane samples no ID return until its outstanding count is zero.
    for (genvar l = 0; l < NumLanes; l++) begin : g_lane
      localparam int unsigned Port = l / 2;
      localparam bit IsRd = (l % 2) == 1;

      wire push = IsRd ? ar_hs[Port] : aw_hs[Port];
      wire pop = IsRd ? rl_hs[Port] : b_hs[Port];
      wire [XbarIdW-1:0] push_id = IsRd ? ar_id[Port] : aw_id[Port];
      wire [XbarIdW-1:0] pop_id = IsRd ? r_id[Port] : b_id[Port];

      logic [15:0] cnt_q;
      logic [3:0] fill_q;
      logic lost_q;
      logic [XbarIdW-1:0] ids_q[IdSlots];
      logic found;
      logic [2:0] found_idx;
      logic other_open;

      always_comb begin
        found = 1'b0;
        found_idx = '0;
        other_open = 1'b0;
        for (int unsigned k = 0; k < IdSlots; k++) begin
          if (!found && (4'(k) < fill_q) && (ids_q[k] == pop_id)) begin
            found = 1'b1;
            found_idx = 3'(k);
          end
          if ((4'(k) < fill_q) && (ids_q[k] != pop_id)) other_open = 1'b1;
        end
      end

      wire pop_ok = pop && (cnt_q != '0);
      wire [15:0] cnt_next = cnt_q + {15'b0, push} - {15'b0, pop_ok};
      wire pop_known = pop && !lost_q && found;
      wire [3:0] fill_pop = fill_q - {3'b0, pop_known};
      wire overflow = push && (fill_pop == 4'(IdSlots));

      always_ff @(posedge clk_smu_i) begin
        if (xbar_in_reset) begin
          cnt_q <= '0;
          fill_q <= '0;
          lost_q <= 1'b0;
          for (int unsigned k = 0; k < IdSlots; k++) ids_q[k] <= '0;
        end else begin
          cnt_q <= cnt_next;
          if (cnt_next == '0) begin
            fill_q <= '0;
            lost_q <= 1'b0;
          end else if (lost_q || overflow) begin
            lost_q <= 1'b1;
          end else begin
            for (int unsigned k = 0; k < IdSlots - 1; k++) begin
              if (pop_known && (3'(k) >= found_idx)) ids_q[k] <= ids_q[k+1];
            end
            if (push) ids_q[fill_pop[2:0]] <= push_id;
            fill_q <= fill_pop + {3'b0, push};
          end
        end
      end

      assign push_v[l] = push;
      assign idle_v[l] = (cnt_q == '0);
      assign depth_v[l] = cnt_q + 16'd1;
      assign depth_1_v[l] = push && (cnt_q == 16'd0);
      assign depth_2_4_v[l] = push && (cnt_q >= 16'd1) && (cnt_q <= 16'd3);
      assign depth_5_8_v[l] = push && (cnt_q >= 16'd4) && (cnt_q <= 16'd7);
      assign depth_gt8_v[l] = push && (cnt_q >= 16'd8);
      assign id_inorder_v[l] = pop_known && (found_idx == 3'd0) && other_open;
      assign id_ooo_v[l] = pop_known && (found_idx != 3'd0);
    end

    // Routing cells, by the SMU crossbar routing table: the initiator and
    // the aperture its address decodes to select sep_in, smc_in, ext_out
    // or DECERR. An aperture is [base, base + size) in a 57-bit sum, and a
    // zero size disables it. An address in both apertures selects no
    // cell. Lane r = 2i + d of initiator i arms on an address phase
    // accepted with nothing outstanding on that lane, records the ID and
    // the selection, and completes on the first B or RLAST of that lane
    // carrying the recorded ID. A forwarding cell arms only when, on the
    // same channel, the selected target port has nothing outstanding and
    // no other initiator has anything outstanding or an address phase in
    // the arming cycle; an address phase on another initiator of that
    // channel before the target handshake disqualifies it. It counts when
    // the selected target port handshakes the same channel after the arming
    // cycle and before the response. A DECERR cell counts when the response
    // is DECERR.
    localparam logic [2:0] PortSepIn = 3'd3;
    localparam logic [2:0] PortSmcIn = 3'd4;
    localparam logic [2:0] PortExtOut = 3'd5;
    localparam logic [2:0] DestNone = 3'd6;
    localparam logic [2:0] DestDecerr = 3'd7;

    wire [56:0] sep_end = {1'b0, sep_global_base_i} + {1'b0, sep_region_size_i};
    wire [56:0] smc_end = {1'b0, smc_global_base_i} + {25'b0, smc_region_size_i};
    logic [NumRouteLanes-1:0] route_fwd_v;
    logic [NumRouteLanes-1:0] route_decerr_v;
    logic [NumRouteLanes-1:0][2:0] route_dest_v;
    logic [NumPorts-1:0] idle_wr;
    logic [NumPorts-1:0] idle_rd;
    for (genvar p = 0; p < NumPorts; p++) begin : g_idle
      assign idle_wr[p] = idle_v[2*p];
      assign idle_rd[p] = idle_v[2*p+1];
    end

    for (genvar r = 0; r < NumRouteLanes; r++) begin : g_route
      localparam int unsigned Init = r / 2;
      localparam bit IsRd = (r % 2) == 1;

      wire hs = IsRd ? ar_hs[Init] : aw_hs[Init];
      wire [55:0] addr = IsRd ? init_araddr[Init] : init_awaddr[Init];
      wire [XbarIdW-1:0] id = IsRd ? ar_id[Init] : aw_id[Init];
      wire resp_hs = IsRd ? rl_hs[Init] : b_hs[Init];
      wire [XbarIdW-1:0] resp_id = IsRd ? r_id[Init] : b_id[Init];
      wire [1:0] resp = IsRd ? init_rresp[Init] : init_bresp[Init];
      wire [NumPorts-1:0] chan_hs = IsRd ? ar_hs : aw_hs;
      wire [NumPorts-1:0] chan_idle = IsRd ? idle_rd : idle_wr;
      wire [7:0] tgt_hs = {2'b00, chan_hs};
      wire [7:0] tgt_idle = {2'b00, chan_idle};
      wire [2:0] others = ~(3'b001 << Init);
      wire others_idle = ((chan_idle[2:0] & others) == others);
      wire others_hs = |(chan_hs[2:0] & others);
      wire in_sep = (sep_region_size_i != '0) && ({1'b0, addr} >= {1'b0, sep_global_base_i})
          && ({1'b0, addr} < sep_end);
      wire in_smc = (smc_region_size_i != '0) && ({1'b0, addr} >= {1'b0, smc_global_base_i})
          && ({1'b0, addr} < smc_end);
      wire [2:0] dest = (in_sep && in_smc) ? DestNone
          : in_sep ? ((Init == 0) ? DestDecerr : PortSepIn)
          : in_smc ? ((Init == 1) ? DestDecerr : PortSmcIn)
          : ((Init == 2) ? DestDecerr : PortExtOut);

      wire sole = (dest == DestDecerr) || (tgt_idle[dest] && others_idle && !others_hs);
      logic armed_q, seen_q, clean_q;
      logic [2:0] dest_q;
      logic [XbarIdW-1:0] id_q;
      wire arm = hs && !armed_q && idle_v[r] && (dest != DestNone) && sole;
      wire done = armed_q && resp_hs && (resp_id == id_q);

      always_ff @(posedge clk_smu_i) begin
        if (xbar_in_reset) begin
          armed_q <= 1'b0;
          seen_q <= 1'b0;
          clean_q <= 1'b0;
          dest_q <= '0;
          id_q <= '0;
        end else if (arm) begin
          armed_q <= 1'b1;
          seen_q <= 1'b0;
          clean_q <= 1'b1;
          dest_q <= dest;
          id_q <= id;
        end else if (done) begin
          armed_q <= 1'b0;
          seen_q <= 1'b0;
          clean_q <= 1'b0;
        end else if (armed_q && !seen_q) begin
          if (others_hs) clean_q <= 1'b0;
          if (tgt_hs[dest_q]) seen_q <= 1'b1;
        end
      end

      assign route_dest_v[r] = dest_q;
      assign route_fwd_v[r] = done && (dest_q != DestDecerr) && seen_q && clean_q;
      assign route_decerr_v[r] = done && (dest_q == DestDecerr) && (resp == 2'b11);
    end

    // Routing cells: c_route_<initiator>_to_<target>_{wr,rd} and
    // c_route_decerr_<initiator>_<aperture>_{wr,rd}.
    wire route_sep_out_to_smc_in_wr_e = route_fwd_v[0] && (route_dest_v[0] == PortSmcIn);
    wire route_sep_out_to_smc_in_rd_e = route_fwd_v[1] && (route_dest_v[1] == PortSmcIn);
    wire route_sep_out_to_ext_out_wr_e = route_fwd_v[0] && (route_dest_v[0] == PortExtOut);
    wire route_sep_out_to_ext_out_rd_e = route_fwd_v[1] && (route_dest_v[1] == PortExtOut);
    wire route_smc_out_to_sep_in_wr_e = route_fwd_v[2] && (route_dest_v[2] == PortSepIn);
    wire route_smc_out_to_sep_in_rd_e = route_fwd_v[3] && (route_dest_v[3] == PortSepIn);
    wire route_smc_out_to_ext_out_wr_e = route_fwd_v[2] && (route_dest_v[2] == PortExtOut);
    wire route_smc_out_to_ext_out_rd_e = route_fwd_v[3] && (route_dest_v[3] == PortExtOut);
    wire route_ext_in_to_sep_in_wr_e = route_fwd_v[4] && (route_dest_v[4] == PortSepIn);
    wire route_ext_in_to_sep_in_rd_e = route_fwd_v[5] && (route_dest_v[5] == PortSepIn);
    wire route_ext_in_to_smc_in_wr_e = route_fwd_v[4] && (route_dest_v[4] == PortSmcIn);
    wire route_ext_in_to_smc_in_rd_e = route_fwd_v[5] && (route_dest_v[5] == PortSmcIn);
    wire route_decerr_sep_out_sep_wr_e = route_decerr_v[0];
    wire route_decerr_sep_out_sep_rd_e = route_decerr_v[1];
    wire route_decerr_smc_out_smc_wr_e = route_decerr_v[2];
    wire route_decerr_smc_out_smc_rd_e = route_decerr_v[3];
    wire route_decerr_ext_in_neither_wr_e = route_decerr_v[4];
    wire route_decerr_ext_in_neither_rd_e = route_decerr_v[5];
    `OCAH_FCOV_COVER(c_route_sep_out_to_smc_in_wr, route_sep_out_to_smc_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_sep_out_to_smc_in_rd, route_sep_out_to_smc_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_sep_out_to_ext_out_wr, route_sep_out_to_ext_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_sep_out_to_ext_out_rd, route_sep_out_to_ext_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_smc_out_to_sep_in_wr, route_smc_out_to_sep_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_smc_out_to_sep_in_rd, route_smc_out_to_sep_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_smc_out_to_ext_out_wr, route_smc_out_to_ext_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_smc_out_to_ext_out_rd, route_smc_out_to_ext_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_ext_in_to_sep_in_wr, route_ext_in_to_sep_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_ext_in_to_sep_in_rd, route_ext_in_to_sep_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_ext_in_to_smc_in_wr, route_ext_in_to_smc_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_ext_in_to_smc_in_rd, route_ext_in_to_smc_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_decerr_sep_out_sep_wr, route_decerr_sep_out_sep_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_decerr_sep_out_sep_rd, route_decerr_sep_out_sep_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_decerr_smc_out_smc_wr, route_decerr_smc_out_smc_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_decerr_smc_out_smc_rd, route_decerr_smc_out_smc_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_decerr_ext_in_neither_wr, route_decerr_ext_in_neither_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_route_decerr_ext_in_neither_rd, route_decerr_ext_in_neither_rd_e, clk_smu_i,
                     xbar_in_reset)

    // Outstanding depth at the address handshake:
    // c_depth_<port>_{wr,rd}_{1,2_4,5_8,gt8}.
    wire depth_sep_out_wr_1_e = depth_1_v[0];
    wire depth_sep_out_wr_2_4_e = depth_2_4_v[0];
    wire depth_sep_out_wr_5_8_e = depth_5_8_v[0];
    wire depth_sep_out_wr_gt8_e = depth_gt8_v[0];
    wire depth_sep_out_rd_1_e = depth_1_v[1];
    wire depth_sep_out_rd_2_4_e = depth_2_4_v[1];
    wire depth_sep_out_rd_5_8_e = depth_5_8_v[1];
    wire depth_sep_out_rd_gt8_e = depth_gt8_v[1];
    wire depth_smc_out_wr_1_e = depth_1_v[2];
    wire depth_smc_out_wr_2_4_e = depth_2_4_v[2];
    wire depth_smc_out_wr_5_8_e = depth_5_8_v[2];
    wire depth_smc_out_wr_gt8_e = depth_gt8_v[2];
    wire depth_smc_out_rd_1_e = depth_1_v[3];
    wire depth_smc_out_rd_2_4_e = depth_2_4_v[3];
    wire depth_smc_out_rd_5_8_e = depth_5_8_v[3];
    wire depth_smc_out_rd_gt8_e = depth_gt8_v[3];
    wire depth_ext_in_wr_1_e = depth_1_v[4];
    wire depth_ext_in_wr_2_4_e = depth_2_4_v[4];
    wire depth_ext_in_wr_5_8_e = depth_5_8_v[4];
    wire depth_ext_in_wr_gt8_e = depth_gt8_v[4];
    wire depth_ext_in_rd_1_e = depth_1_v[5];
    wire depth_ext_in_rd_2_4_e = depth_2_4_v[5];
    wire depth_ext_in_rd_5_8_e = depth_5_8_v[5];
    wire depth_ext_in_rd_gt8_e = depth_gt8_v[5];
    wire depth_sep_in_wr_1_e = depth_1_v[6];
    wire depth_sep_in_wr_2_4_e = depth_2_4_v[6];
    wire depth_sep_in_wr_5_8_e = depth_5_8_v[6];
    wire depth_sep_in_wr_gt8_e = depth_gt8_v[6];
    wire depth_sep_in_rd_1_e = depth_1_v[7];
    wire depth_sep_in_rd_2_4_e = depth_2_4_v[7];
    wire depth_sep_in_rd_5_8_e = depth_5_8_v[7];
    wire depth_sep_in_rd_gt8_e = depth_gt8_v[7];
    wire depth_smc_in_wr_1_e = depth_1_v[8];
    wire depth_smc_in_wr_2_4_e = depth_2_4_v[8];
    wire depth_smc_in_wr_5_8_e = depth_5_8_v[8];
    wire depth_smc_in_wr_gt8_e = depth_gt8_v[8];
    wire depth_smc_in_rd_1_e = depth_1_v[9];
    wire depth_smc_in_rd_2_4_e = depth_2_4_v[9];
    wire depth_smc_in_rd_5_8_e = depth_5_8_v[9];
    wire depth_smc_in_rd_gt8_e = depth_gt8_v[9];
    wire depth_ext_out_wr_1_e = depth_1_v[10];
    wire depth_ext_out_wr_2_4_e = depth_2_4_v[10];
    wire depth_ext_out_wr_5_8_e = depth_5_8_v[10];
    wire depth_ext_out_wr_gt8_e = depth_gt8_v[10];
    wire depth_ext_out_rd_1_e = depth_1_v[11];
    wire depth_ext_out_rd_2_4_e = depth_2_4_v[11];
    wire depth_ext_out_rd_5_8_e = depth_5_8_v[11];
    wire depth_ext_out_rd_gt8_e = depth_gt8_v[11];
    `OCAH_FCOV_COVER(c_depth_sep_out_wr_1, depth_sep_out_wr_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_wr_2_4, depth_sep_out_wr_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_wr_5_8, depth_sep_out_wr_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_wr_gt8, depth_sep_out_wr_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_rd_1, depth_sep_out_rd_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_rd_2_4, depth_sep_out_rd_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_rd_5_8, depth_sep_out_rd_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_out_rd_gt8, depth_sep_out_rd_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_wr_1, depth_smc_out_wr_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_wr_2_4, depth_smc_out_wr_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_wr_5_8, depth_smc_out_wr_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_wr_gt8, depth_smc_out_wr_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_rd_1, depth_smc_out_rd_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_rd_2_4, depth_smc_out_rd_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_rd_5_8, depth_smc_out_rd_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_out_rd_gt8, depth_smc_out_rd_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_wr_1, depth_ext_in_wr_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_wr_2_4, depth_ext_in_wr_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_wr_5_8, depth_ext_in_wr_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_wr_gt8, depth_ext_in_wr_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_rd_1, depth_ext_in_rd_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_rd_2_4, depth_ext_in_rd_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_rd_5_8, depth_ext_in_rd_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_in_rd_gt8, depth_ext_in_rd_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_wr_1, depth_sep_in_wr_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_wr_2_4, depth_sep_in_wr_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_wr_5_8, depth_sep_in_wr_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_wr_gt8, depth_sep_in_wr_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_rd_1, depth_sep_in_rd_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_rd_2_4, depth_sep_in_rd_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_rd_5_8, depth_sep_in_rd_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_sep_in_rd_gt8, depth_sep_in_rd_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_wr_1, depth_smc_in_wr_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_wr_2_4, depth_smc_in_wr_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_wr_5_8, depth_smc_in_wr_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_wr_gt8, depth_smc_in_wr_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_rd_1, depth_smc_in_rd_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_rd_2_4, depth_smc_in_rd_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_rd_5_8, depth_smc_in_rd_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_smc_in_rd_gt8, depth_smc_in_rd_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_wr_1, depth_ext_out_wr_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_wr_2_4, depth_ext_out_wr_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_wr_5_8, depth_ext_out_wr_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_wr_gt8, depth_ext_out_wr_gt8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_rd_1, depth_ext_out_rd_1_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_rd_2_4, depth_ext_out_rd_2_4_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_rd_5_8, depth_ext_out_rd_5_8_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_depth_ext_out_rd_gt8, depth_ext_out_rd_gt8_e, clk_smu_i, xbar_in_reset)

    // ID return order: c_id_return_{inorder,ooo}_<port>_{wr,rd}.
    wire id_return_inorder_sep_out_wr_e = id_inorder_v[0];
    wire id_return_ooo_sep_out_wr_e = id_ooo_v[0];
    wire id_return_inorder_sep_out_rd_e = id_inorder_v[1];
    wire id_return_ooo_sep_out_rd_e = id_ooo_v[1];
    wire id_return_inorder_smc_out_wr_e = id_inorder_v[2];
    wire id_return_ooo_smc_out_wr_e = id_ooo_v[2];
    wire id_return_inorder_smc_out_rd_e = id_inorder_v[3];
    wire id_return_ooo_smc_out_rd_e = id_ooo_v[3];
    wire id_return_inorder_ext_in_wr_e = id_inorder_v[4];
    wire id_return_ooo_ext_in_wr_e = id_ooo_v[4];
    wire id_return_inorder_ext_in_rd_e = id_inorder_v[5];
    wire id_return_ooo_ext_in_rd_e = id_ooo_v[5];
    wire id_return_inorder_sep_in_wr_e = id_inorder_v[6];
    wire id_return_ooo_sep_in_wr_e = id_ooo_v[6];
    wire id_return_inorder_sep_in_rd_e = id_inorder_v[7];
    wire id_return_ooo_sep_in_rd_e = id_ooo_v[7];
    wire id_return_inorder_smc_in_wr_e = id_inorder_v[8];
    wire id_return_ooo_smc_in_wr_e = id_ooo_v[8];
    wire id_return_inorder_smc_in_rd_e = id_inorder_v[9];
    wire id_return_ooo_smc_in_rd_e = id_ooo_v[9];
    wire id_return_inorder_ext_out_wr_e = id_inorder_v[10];
    wire id_return_ooo_ext_out_wr_e = id_ooo_v[10];
    wire id_return_inorder_ext_out_rd_e = id_inorder_v[11];
    wire id_return_ooo_ext_out_rd_e = id_ooo_v[11];
    `OCAH_FCOV_COVER(c_id_return_inorder_sep_out_wr, id_return_inorder_sep_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_sep_out_wr, id_return_ooo_sep_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_sep_out_rd, id_return_inorder_sep_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_sep_out_rd, id_return_ooo_sep_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_smc_out_wr, id_return_inorder_smc_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_smc_out_wr, id_return_ooo_smc_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_smc_out_rd, id_return_inorder_smc_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_smc_out_rd, id_return_ooo_smc_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_ext_in_wr, id_return_inorder_ext_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_ext_in_wr, id_return_ooo_ext_in_wr_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_ext_in_rd, id_return_inorder_ext_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_ext_in_rd, id_return_ooo_ext_in_rd_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_sep_in_wr, id_return_inorder_sep_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_sep_in_wr, id_return_ooo_sep_in_wr_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_sep_in_rd, id_return_inorder_sep_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_sep_in_rd, id_return_ooo_sep_in_rd_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_smc_in_wr, id_return_inorder_smc_in_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_smc_in_wr, id_return_ooo_smc_in_wr_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_smc_in_rd, id_return_inorder_smc_in_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_smc_in_rd, id_return_ooo_smc_in_rd_e, clk_smu_i, xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_ext_out_wr, id_return_inorder_ext_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_ext_out_wr, id_return_ooo_ext_out_wr_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_inorder_ext_out_rd, id_return_inorder_ext_out_rd_e, clk_smu_i,
                     xbar_in_reset)
    `OCAH_FCOV_COVER(c_id_return_ooo_ext_out_rd, id_return_ooo_ext_out_rd_e, clk_smu_i,
                     xbar_in_reset)

`ifndef VERILATOR
    // Covergroups: the same three families for the commercial flow, one
    // instance per direction, sampled on the handshake that credits the
    // matching point.
    covergroup cg_xbar_route with function sample (logic [5:0] route_cell);
      option.per_instance = 1;
      cp_cell: coverpoint route_cell {
        bins sep_out_to_smc_in = {6'o04};
        bins sep_out_to_ext_out = {6'o05};
        bins smc_out_to_sep_in = {6'o13};
        bins smc_out_to_ext_out = {6'o15};
        bins ext_in_to_sep_in = {6'o23};
        bins ext_in_to_smc_in = {6'o24};
        bins decerr_sep_out_sep = {6'o07};
        bins decerr_smc_out_smc = {6'o17};
        bins decerr_ext_in_neither = {6'o27};
      }
    endgroup

    covergroup cg_xbar_depth with function sample (logic [2:0] port, logic [15:0] depth);
      option.per_instance = 1;
      cp_port: coverpoint port {
        bins sep_out = {3'd0};
        bins smc_out = {3'd1};
        bins ext_in = {3'd2};
        bins sep_in = {3'd3};
        bins smc_in = {3'd4};
        bins ext_out = {3'd5};
      }
      cp_depth: coverpoint depth {
        bins one = {1};
        bins two_to_four = {[2 : 4]};
        bins five_to_eight = {[5 : 8]};
        bins over_eight = {[9 : $]};
      }
      x_port_depth: cross cp_port, cp_depth;
    endgroup

    covergroup cg_xbar_id_return with function sample (logic [2:0] port, logic ooo);
      option.per_instance = 1;
      cp_port: coverpoint port {
        bins sep_out = {3'd0};
        bins smc_out = {3'd1};
        bins ext_in = {3'd2};
        bins sep_in = {3'd3};
        bins smc_in = {3'd4};
        bins ext_out = {3'd5};
      }
      cp_order: coverpoint ooo {bins in_order = {1'b0}; bins out_of_order = {1'b1};}
      x_port_order: cross cp_port, cp_order;
    endgroup

    cg_xbar_route u_cg_route_wr = new();
    cg_xbar_route u_cg_route_rd = new();
    cg_xbar_depth u_cg_depth_wr = new();
    cg_xbar_depth u_cg_depth_rd = new();
    cg_xbar_id_return u_cg_id_return_wr = new();
    cg_xbar_id_return u_cg_id_return_rd = new();

    always_ff @(posedge clk_smu_i) begin
      if (!xbar_in_reset) begin
        for (int unsigned l = 0; l < NumLanes; l += 2) begin
          if (push_v[l]) u_cg_depth_wr.sample(3'(l / 2), depth_v[l]);
          if (push_v[l+1]) u_cg_depth_rd.sample(3'(l / 2), depth_v[l+1]);
          if (id_inorder_v[l] || id_ooo_v[l]) u_cg_id_return_wr.sample(3'(l / 2), id_ooo_v[l]);
          if (id_inorder_v[l+1] || id_ooo_v[l+1]) begin
            u_cg_id_return_rd.sample(3'(l / 2), id_ooo_v[l+1]);
          end
        end
        for (int unsigned r = 0; r < NumRouteLanes; r += 2) begin
          if (route_fwd_v[r] || route_decerr_v[r]) begin
            u_cg_route_wr.sample({3'(r / 2), route_dest_v[r]});
          end
          if (route_fwd_v[r+1] || route_decerr_v[r+1]) begin
            u_cg_route_rd.sample({3'(r / 2), route_dest_v[r+1]});
          end
        end
      end
    end
`endif
  end

  // ------------------------------------------------------------------
  // Inbound AXI handshake and response codes. EXOKAY answers an exclusive
  // access, and no subordinate behind the crossbar has an exclusive monitor:
  // every AXI interconnect in the SEP and SMC is built without atomics and
  // the memory adapters tie exokay off. Its two points are Phase 2
  // (SMU_FCOV.adoc).
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
  wire bresp_slverr_e = b_accept && (s_axi_bresp_i == 2'b10);
  wire bresp_decerr_e = b_accept && (s_axi_bresp_i == 2'b11);
  wire rresp_okay_e = r_accept && (s_axi_rresp_i == 2'b00);
  wire rresp_slverr_e = r_accept && (s_axi_rresp_i == 2'b10);
  wire rresp_decerr_e = r_accept && (s_axi_rresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_axi_in_bresp_okay, bresp_okay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_bresp_slverr, bresp_slverr_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_bresp_decerr, bresp_decerr_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_okay, rresp_okay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_slverr, rresp_slverr_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_decerr, rresp_decerr_e, clk_smu_i, in_reset)
`ifdef SMU_FCOV_PHASE2
  wire bresp_exokay_e = b_accept && (s_axi_bresp_i == 2'b01);
  wire rresp_exokay_e = r_accept && (s_axi_rresp_i == 2'b01);
  `OCAH_FCOV_COVER(c_axi_in_bresp_exokay, bresp_exokay_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_axi_in_rresp_exokay, rresp_exokay_e, clk_smu_i, in_reset)
`endif

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

  // ------------------------------------------------------------------
  // Covergroups: the response-code distribution and the programmed-window
  // cross a flat point list cannot express.
  // ------------------------------------------------------------------
  covergroup cg_axi_in_resp with function sample (logic [1:0] resp);
    option.per_instance = 1;
    cp_resp: coverpoint resp {
      bins okay = {2'b00};
      bins slverr = {2'b10};
      bins decerr = {2'b11};
      // No subordinate behind the crossbar answers an exclusive access.
      ignore_bins exokay = {2'b01};
    }
  endgroup

  // A zero SMC REGION_SIZE is illegal (smc_base_config: a non-zero power of
  // two), so only the non-zero window is graded.
  covergroup cg_map_window with function sample (logic prog, logic zero);
    option.per_instance = 1;
    cp_prog: coverpoint prog;
    cp_zero: coverpoint zero {ignore_bins illegal_size = {1'b1};}
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

endmodule : smu_xbar_fcov
