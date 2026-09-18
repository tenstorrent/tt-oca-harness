// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive AXI4 wire harness for the shared AXI VIP selftests. No DUT RTL:
// cocotb attaches VIP components to these nets from both sides.
//
//   s_axi_* — full-stack bundle: OcahAxiMasterAgent (drives AW/W/AR plus
//             R/B ready) against OcahAxiSlaveAgent (drives ready plus B/R).
//   t_axi_* — wire-level bundle: the test drives the request channels
//             directly against OcahAxiSlaveAgent so armed response-ID
//             corruption is observable without a backend master in the
//             loop (the cocotbext master rejects a response ID it
//             never issued).
//   l_axi_* — AXI4-Lite bundle: OcahAxiLiteMasterAgent against
//             OcahAxiLiteSlaveAgent, for the lite protocol-control
//             selftests (AW/W launch skew, deferred BREADY/RREADY,
//             partial strobes) with the handshakes observable at the
//             nets.
//   u_wide_axi_if, u_wide_axil_if — default-geometry ocah_axi_if instances
//             (64-bit address and data, 16-bit ID and user); the geometry
//             selftests bind the 32-bit VIP stacks to them through
//             OcahAxiConfig so the member bits above the configured
//             geometry are observable.
//   mt_axi_* — struct-port bundle: the request nets are packed into a pulp
//             request struct, the shape a block tb_top hands the boundary,
//             ocah_axi_struct_bridge places that struct on u_mt_axi_if, and
//             the shared slave agent answers there; the response struct is
//             unpacked back onto the nets.
//
// ocah_axi_sva watches the VIP-driven bundles: mt_axi in both shapes, s_axi
// and l_axi in the cocotb shape. t_axi and, in the SV-UVM shape, u_axi_if
// carry the armed response-ID corruption of the mismatch selftests, where
// the ID-ordering rules must fire, so no checker is bound to them.
//
// In the SV-UVM shape one ocah_axi_cov_if (cov/ocah_axi_cov.sv) is the
// covergroup sampler of both passive envs, published as axi_cov_vif.
//
// The request nets are driven from cocotb (--public-flat-rw) or, in the
// SV-UVM shape, bridged from the ocah_axi_if instances below; the lint
// waivers cover the undriven cocotb-owned nets, which the cocotb shape
// starts at zero.

`timescale 1ns / 1ps

`include "axi/typedef.svh"

module ocah_axi_vip_tb_top;

  /* verilator lint_off UNDRIVEN */
  /* verilator lint_off UNUSEDSIGNAL */

  logic clk;
  logic rst_n;

  // ------------------------------------------------------------------
  // s_axi: full-stack bundle (VIP master <-> VIP fault slave)
  // ------------------------------------------------------------------
  logic [7:0]  s_axi_awid;
  logic [31:0] s_axi_awaddr;
  logic [7:0]  s_axi_awlen;
  logic [2:0]  s_axi_awsize;
  logic [1:0]  s_axi_awburst;
  logic        s_axi_awlock;
  logic [3:0]  s_axi_awcache;
  logic [2:0]  s_axi_awprot;
  logic [3:0]  s_axi_awqos;
  logic [3:0]  s_axi_awregion;
  logic        s_axi_awvalid;
  logic        s_axi_awready;

  logic [31:0] s_axi_wdata;
  logic [3:0]  s_axi_wstrb;
  logic        s_axi_wlast;
  logic        s_axi_wvalid;
  logic        s_axi_wready;

  logic [7:0]  s_axi_bid;
  logic [1:0]  s_axi_bresp;
  logic        s_axi_bvalid;
  logic        s_axi_bready;

  logic [7:0]  s_axi_arid;
  logic [31:0] s_axi_araddr;
  logic [7:0]  s_axi_arlen;
  logic [2:0]  s_axi_arsize;
  logic [1:0]  s_axi_arburst;
  logic        s_axi_arlock;
  logic [3:0]  s_axi_arcache;
  logic [2:0]  s_axi_arprot;
  logic [3:0]  s_axi_arqos;
  logic [3:0]  s_axi_arregion;
  logic        s_axi_arvalid;
  logic        s_axi_arready;

  logic [7:0]  s_axi_rid;
  logic [31:0] s_axi_rdata;
  logic [1:0]  s_axi_rresp;
  logic        s_axi_rlast;
  logic        s_axi_rvalid;
  logic        s_axi_rready;

  // Optional user sidebands (the master backend rejects its defaulted user
  // arguments when these are absent).
  logic        s_axi_awuser;
  logic        s_axi_wuser;
  logic        s_axi_buser;
  logic        s_axi_aruser;
  logic        s_axi_ruser;

  // ------------------------------------------------------------------
  // t_axi: wire-level bundle (test-driven requests <-> VIP fault slave)
  // ------------------------------------------------------------------
  logic [7:0]  t_axi_awid;
  logic [31:0] t_axi_awaddr;
  logic [7:0]  t_axi_awlen;
  logic [2:0]  t_axi_awsize;
  logic [1:0]  t_axi_awburst;
  logic        t_axi_awlock;
  logic [3:0]  t_axi_awcache;
  logic [2:0]  t_axi_awprot;
  logic [3:0]  t_axi_awqos;
  logic [3:0]  t_axi_awregion;
  logic        t_axi_awvalid;
  logic        t_axi_awready;

  logic [31:0] t_axi_wdata;
  logic [3:0]  t_axi_wstrb;
  logic        t_axi_wlast;
  logic        t_axi_wvalid;
  logic        t_axi_wready;

  logic [7:0]  t_axi_bid;
  logic [1:0]  t_axi_bresp;
  logic        t_axi_bvalid;
  logic        t_axi_bready;

  logic [7:0]  t_axi_arid;
  logic [31:0] t_axi_araddr;
  logic [7:0]  t_axi_arlen;
  logic [2:0]  t_axi_arsize;
  logic [1:0]  t_axi_arburst;
  logic        t_axi_arlock;
  logic [3:0]  t_axi_arcache;
  logic [2:0]  t_axi_arprot;
  logic [3:0]  t_axi_arqos;
  logic [3:0]  t_axi_arregion;
  logic        t_axi_arvalid;
  logic        t_axi_arready;

  logic [7:0]  t_axi_rid;
  logic [31:0] t_axi_rdata;
  logic [1:0]  t_axi_rresp;
  logic        t_axi_rlast;
  logic        t_axi_rvalid;
  logic        t_axi_rready;

  // ------------------------------------------------------------------
  // l_axi: AXI4-Lite bundle (VIP lite master <-> VIP lite RAM slave)
  // ------------------------------------------------------------------
  logic [31:0] l_axi_awaddr;
  logic [2:0]  l_axi_awprot;
  logic        l_axi_awvalid;
  logic        l_axi_awready;

  logic [31:0] l_axi_wdata;
  logic [3:0]  l_axi_wstrb;
  logic        l_axi_wvalid;
  logic        l_axi_wready;

  logic [1:0]  l_axi_bresp;
  logic        l_axi_bvalid;
  logic        l_axi_bready;

  logic [31:0] l_axi_araddr;
  logic [2:0]  l_axi_arprot;
  logic        l_axi_arvalid;
  logic        l_axi_arready;

  logic [31:0] l_axi_rdata;
  logic [1:0]  l_axi_rresp;
  logic        l_axi_rvalid;
  logic        l_axi_rready;

  // ------------------------------------------------------------------
  // mt_axi: struct-port bundle (VIP master <-> struct bridge <-> VIP slave agent)
  // ------------------------------------------------------------------
  logic [7:0]  mt_axi_awid;
  logic [31:0] mt_axi_awaddr;
  logic [7:0]  mt_axi_awlen;
  logic [2:0]  mt_axi_awsize;
  logic [1:0]  mt_axi_awburst;
  logic        mt_axi_awlock;
  logic [3:0]  mt_axi_awcache;
  logic [2:0]  mt_axi_awprot;
  logic [3:0]  mt_axi_awqos;
  logic [3:0]  mt_axi_awregion;
  logic        mt_axi_awuser;
  logic        mt_axi_awvalid;
  logic        mt_axi_awready;

  logic [31:0] mt_axi_wdata;
  logic [3:0]  mt_axi_wstrb;
  logic        mt_axi_wlast;
  logic        mt_axi_wuser;
  logic        mt_axi_wvalid;
  logic        mt_axi_wready;

  logic [7:0]  mt_axi_bid;
  logic [1:0]  mt_axi_bresp;
  logic        mt_axi_buser;
  logic        mt_axi_bvalid;
  logic        mt_axi_bready;

  logic [7:0]  mt_axi_arid;
  logic [31:0] mt_axi_araddr;
  logic [7:0]  mt_axi_arlen;
  logic [2:0]  mt_axi_arsize;
  logic [1:0]  mt_axi_arburst;
  logic        mt_axi_arlock;
  logic [3:0]  mt_axi_arcache;
  logic [2:0]  mt_axi_arprot;
  logic [3:0]  mt_axi_arqos;
  logic [3:0]  mt_axi_arregion;
  logic        mt_axi_aruser;
  logic        mt_axi_arvalid;
  logic        mt_axi_arready;

  logic [7:0]  mt_axi_rid;
  logic [31:0] mt_axi_rdata;
  logic [1:0]  mt_axi_rresp;
  logic        mt_axi_rlast;
  logic        mt_axi_ruser;
  logic        mt_axi_rvalid;
  logic        mt_axi_rready;

  /* verilator lint_on UNUSEDSIGNAL */
  /* verilator lint_on UNDRIVEN */

`ifndef UVM
  // The cocotb-owned nets and the responder-side members of the struct
  // bridge's interface start at zero: a test binds VIPs to its own bundles
  // only, and the reset-low and known-value rules of the bound checkers
  // judge every bundle from time zero on a four-state simulator.
  initial begin
    u_mt_axi_if.awready = '0;
    u_mt_axi_if.wready  = '0;
    u_mt_axi_if.bid     = '0;
    u_mt_axi_if.bresp   = '0;
    u_mt_axi_if.buser   = '0;
    u_mt_axi_if.bvalid  = '0;
    u_mt_axi_if.arready = '0;
    u_mt_axi_if.rid     = '0;
    u_mt_axi_if.rdata   = '0;
    u_mt_axi_if.rresp   = '0;
    u_mt_axi_if.rlast   = '0;
    u_mt_axi_if.ruser   = '0;
    u_mt_axi_if.rvalid  = '0;
    s_axi_awid = '0;
    s_axi_awaddr = '0;
    s_axi_awlen = '0;
    s_axi_awsize = '0;
    s_axi_awburst = '0;
    s_axi_awlock = '0;
    s_axi_awcache = '0;
    s_axi_awprot = '0;
    s_axi_awqos = '0;
    s_axi_awregion = '0;
    s_axi_awvalid = '0;
    s_axi_awready = '0;
    s_axi_wdata = '0;
    s_axi_wstrb = '0;
    s_axi_wlast = '0;
    s_axi_wvalid = '0;
    s_axi_wready = '0;
    s_axi_bid = '0;
    s_axi_bresp = '0;
    s_axi_bvalid = '0;
    s_axi_bready = '0;
    s_axi_arid = '0;
    s_axi_araddr = '0;
    s_axi_arlen = '0;
    s_axi_arsize = '0;
    s_axi_arburst = '0;
    s_axi_arlock = '0;
    s_axi_arcache = '0;
    s_axi_arprot = '0;
    s_axi_arqos = '0;
    s_axi_arregion = '0;
    s_axi_arvalid = '0;
    s_axi_arready = '0;
    s_axi_rid = '0;
    s_axi_rdata = '0;
    s_axi_rresp = '0;
    s_axi_rlast = '0;
    s_axi_rvalid = '0;
    s_axi_rready = '0;
    s_axi_awuser = '0;
    s_axi_wuser = '0;
    s_axi_buser = '0;
    s_axi_aruser = '0;
    s_axi_ruser = '0;
    t_axi_awid = '0;
    t_axi_awaddr = '0;
    t_axi_awlen = '0;
    t_axi_awsize = '0;
    t_axi_awburst = '0;
    t_axi_awlock = '0;
    t_axi_awcache = '0;
    t_axi_awprot = '0;
    t_axi_awqos = '0;
    t_axi_awregion = '0;
    t_axi_awvalid = '0;
    t_axi_awready = '0;
    t_axi_wdata = '0;
    t_axi_wstrb = '0;
    t_axi_wlast = '0;
    t_axi_wvalid = '0;
    t_axi_wready = '0;
    t_axi_bid = '0;
    t_axi_bresp = '0;
    t_axi_bvalid = '0;
    t_axi_bready = '0;
    t_axi_arid = '0;
    t_axi_araddr = '0;
    t_axi_arlen = '0;
    t_axi_arsize = '0;
    t_axi_arburst = '0;
    t_axi_arlock = '0;
    t_axi_arcache = '0;
    t_axi_arprot = '0;
    t_axi_arqos = '0;
    t_axi_arregion = '0;
    t_axi_arvalid = '0;
    t_axi_arready = '0;
    t_axi_rid = '0;
    t_axi_rdata = '0;
    t_axi_rresp = '0;
    t_axi_rlast = '0;
    t_axi_rvalid = '0;
    t_axi_rready = '0;
    l_axi_awaddr = '0;
    l_axi_awprot = '0;
    l_axi_awvalid = '0;
    l_axi_awready = '0;
    l_axi_wdata = '0;
    l_axi_wstrb = '0;
    l_axi_wvalid = '0;
    l_axi_wready = '0;
    l_axi_bresp = '0;
    l_axi_bvalid = '0;
    l_axi_bready = '0;
    l_axi_araddr = '0;
    l_axi_arprot = '0;
    l_axi_arvalid = '0;
    l_axi_arready = '0;
    l_axi_rdata = '0;
    l_axi_rresp = '0;
    l_axi_rvalid = '0;
    l_axi_rready = '0;
    mt_axi_awid = '0;
    mt_axi_awaddr = '0;
    mt_axi_awlen = '0;
    mt_axi_awsize = '0;
    mt_axi_awburst = '0;
    mt_axi_awlock = '0;
    mt_axi_awcache = '0;
    mt_axi_awprot = '0;
    mt_axi_awqos = '0;
    mt_axi_awregion = '0;
    mt_axi_awuser = '0;
    mt_axi_awvalid = '0;
    mt_axi_wdata = '0;
    mt_axi_wstrb = '0;
    mt_axi_wlast = '0;
    mt_axi_wuser = '0;
    mt_axi_wvalid = '0;
    mt_axi_bready = '0;
    mt_axi_arid = '0;
    mt_axi_araddr = '0;
    mt_axi_arlen = '0;
    mt_axi_arsize = '0;
    mt_axi_arburst = '0;
    mt_axi_arlock = '0;
    mt_axi_arcache = '0;
    mt_axi_arprot = '0;
    mt_axi_arqos = '0;
    mt_axi_arregion = '0;
    mt_axi_aruser = '0;
    mt_axi_arvalid = '0;
    mt_axi_rready = '0;
  end
`endif

  // ------------------------------------------------------------------
  // Struct-port boundary under test (both shapes): the mt_axi request nets
  // packed into a pulp struct, bridged onto u_mt_axi_if for the slave agent.
  // ------------------------------------------------------------------
  `AXI_TYPEDEF_ALL(mt, logic [31:0], logic [7:0], logic [31:0], logic [3:0], logic [0:0])

  mt_req_t  mt_req;
  mt_resp_t mt_resp;

  always_comb begin
    mt_req           = '0;
    mt_req.aw.id     = mt_axi_awid;
    mt_req.aw.addr   = mt_axi_awaddr;
    mt_req.aw.len    = mt_axi_awlen;
    mt_req.aw.size   = mt_axi_awsize;
    mt_req.aw.burst  = mt_axi_awburst;
    mt_req.aw.lock   = mt_axi_awlock;
    mt_req.aw.cache  = mt_axi_awcache;
    mt_req.aw.prot   = mt_axi_awprot;
    mt_req.aw.qos    = mt_axi_awqos;
    mt_req.aw.region = mt_axi_awregion;
    mt_req.aw.user   = mt_axi_awuser;
    mt_req.aw_valid  = mt_axi_awvalid;
    mt_req.w.data    = mt_axi_wdata;
    mt_req.w.strb    = mt_axi_wstrb;
    mt_req.w.last    = mt_axi_wlast;
    mt_req.w.user    = mt_axi_wuser;
    mt_req.w_valid   = mt_axi_wvalid;
    mt_req.b_ready   = mt_axi_bready;
    mt_req.ar.id     = mt_axi_arid;
    mt_req.ar.addr   = mt_axi_araddr;
    mt_req.ar.len    = mt_axi_arlen;
    mt_req.ar.size   = mt_axi_arsize;
    mt_req.ar.burst  = mt_axi_arburst;
    mt_req.ar.lock   = mt_axi_arlock;
    mt_req.ar.cache  = mt_axi_arcache;
    mt_req.ar.prot   = mt_axi_arprot;
    mt_req.ar.qos    = mt_axi_arqos;
    mt_req.ar.region = mt_axi_arregion;
    mt_req.ar.user   = mt_axi_aruser;
    mt_req.ar_valid  = mt_axi_arvalid;
    mt_req.r_ready   = mt_axi_rready;
  end

  assign mt_axi_awready = mt_resp.aw_ready;
  assign mt_axi_wready  = mt_resp.w_ready;
  assign mt_axi_bid     = mt_resp.b.id;
  assign mt_axi_bresp   = mt_resp.b.resp;
  assign mt_axi_buser   = mt_resp.b.user;
  assign mt_axi_bvalid  = mt_resp.b_valid;
  assign mt_axi_arready = mt_resp.ar_ready;
  assign mt_axi_rid     = mt_resp.r.id;
  assign mt_axi_rdata   = mt_resp.r.data;
  assign mt_axi_rresp   = mt_resp.r.resp;
  assign mt_axi_rlast   = mt_resp.r.last;
  assign mt_axi_ruser   = mt_resp.r.user;
  assign mt_axi_rvalid  = mt_resp.r_valid;

  ocah_axi_if u_mt_axi_if (
    .aclk(clk),
    .aresetn(rst_n)
  );

  ocah_axi_struct_bridge #(
    .axi_req_t  (mt_req_t),
    .axi_resp_t (mt_resp_t)
  ) u_mt_bridge (
    .axi_req_i  (mt_req),
    .axi_resp_o (mt_resp),
    .axi_if     (u_mt_axi_if)
  );

  // ------------------------------------------------------------------
  // Protocol rules on the struct-port bundle (both shapes)
  // ------------------------------------------------------------------
  ocah_axi_sva #(
    .IS_LITE    (1'b0),
    .ADDR_WIDTH (32),
    .DATA_WIDTH (32),
    .ID_WIDTH   (8)
  ) u_mt_axi_sva (
    .aclk    (clk),
    .aresetn (rst_n),
    .en_i    (1'b1),
    .awid    (mt_axi_awid),
    .awaddr  (mt_axi_awaddr),
    .awlen   (mt_axi_awlen),
    .awsize  (mt_axi_awsize),
    .awburst (mt_axi_awburst),
    .awlock  (mt_axi_awlock),
    .awprot  (mt_axi_awprot),
    .awvalid (mt_axi_awvalid),
    .awready (mt_axi_awready),
    .wdata   (mt_axi_wdata),
    .wstrb   (mt_axi_wstrb),
    .wlast   (mt_axi_wlast),
    .wvalid  (mt_axi_wvalid),
    .wready  (mt_axi_wready),
    .bid     (mt_axi_bid),
    .bresp   (mt_axi_bresp),
    .bvalid  (mt_axi_bvalid),
    .bready  (mt_axi_bready),
    .arid    (mt_axi_arid),
    .araddr  (mt_axi_araddr),
    .arlen   (mt_axi_arlen),
    .arsize  (mt_axi_arsize),
    .arburst (mt_axi_arburst),
    .arlock  (mt_axi_arlock),
    .arprot  (mt_axi_arprot),
    .arvalid (mt_axi_arvalid),
    .arready (mt_axi_arready),
    .rid     (mt_axi_rid),
    .rdata   (mt_axi_rdata),
    .rresp   (mt_axi_rresp),
    .rlast   (mt_axi_rlast),
    .rvalid  (mt_axi_rvalid),
    .rready  (mt_axi_rready)
  );

`ifndef UVM
  // ------------------------------------------------------------------
  // wide: default-geometry ocah_axi_if instances (cocotb shape)
  // ------------------------------------------------------------------
  ocah_axi_if u_wide_axi_if (
    .aclk(clk),
    .aresetn(rst_n)
  );
  ocah_axi_if u_wide_axil_if (
    .aclk(clk),
    .aresetn(rst_n)
  );

  // ------------------------------------------------------------------
  // Protocol rules on the VIP-driven cocotb bundles (s_axi, l_axi)
  // ------------------------------------------------------------------
  ocah_axi_sva #(
    .IS_LITE    (1'b0),
    .ADDR_WIDTH (32),
    .DATA_WIDTH (32),
    .ID_WIDTH   (8)
  ) u_s_axi_sva (
    .aclk    (clk),
    .aresetn (rst_n),
    .en_i    (1'b1),
    .awid    (s_axi_awid),
    .awaddr  (s_axi_awaddr),
    .awlen   (s_axi_awlen),
    .awsize  (s_axi_awsize),
    .awburst (s_axi_awburst),
    .awlock  (s_axi_awlock),
    .awprot  (s_axi_awprot),
    .awvalid (s_axi_awvalid),
    .awready (s_axi_awready),
    .wdata   (s_axi_wdata),
    .wstrb   (s_axi_wstrb),
    .wlast   (s_axi_wlast),
    .wvalid  (s_axi_wvalid),
    .wready  (s_axi_wready),
    .bid     (s_axi_bid),
    .bresp   (s_axi_bresp),
    .bvalid  (s_axi_bvalid),
    .bready  (s_axi_bready),
    .arid    (s_axi_arid),
    .araddr  (s_axi_araddr),
    .arlen   (s_axi_arlen),
    .arsize  (s_axi_arsize),
    .arburst (s_axi_arburst),
    .arlock  (s_axi_arlock),
    .arprot  (s_axi_arprot),
    .arvalid (s_axi_arvalid),
    .arready (s_axi_arready),
    .rid     (s_axi_rid),
    .rdata   (s_axi_rdata),
    .rresp   (s_axi_rresp),
    .rlast   (s_axi_rlast),
    .rvalid  (s_axi_rvalid),
    .rready  (s_axi_rready)
  );

  ocah_axi_sva #(
    .IS_LITE    (1'b1),
    .ADDR_WIDTH (32),
    .DATA_WIDTH (32),
    .ID_WIDTH   (1)
  ) u_l_axi_sva (
    .aclk    (clk),
    .aresetn (rst_n),
    .en_i    (1'b1),
    .awid    ('0),
    .awaddr  (l_axi_awaddr),
    .awlen   ('0),
    .awsize  (3'd2),
    .awburst (2'b01),
    .awlock  (1'b0),
    .awprot  (l_axi_awprot),
    .awvalid (l_axi_awvalid),
    .awready (l_axi_awready),
    .wdata   (l_axi_wdata),
    .wstrb   (l_axi_wstrb),
    .wlast   (1'b1),
    .wvalid  (l_axi_wvalid),
    .wready  (l_axi_wready),
    .bid     ('0),
    .bresp   (l_axi_bresp),
    .bvalid  (l_axi_bvalid),
    .bready  (l_axi_bready),
    .arid    ('0),
    .araddr  (l_axi_araddr),
    .arlen   ('0),
    .arsize  (3'd2),
    .arburst (2'b01),
    .arlock  (1'b0),
    .arprot  (l_axi_arprot),
    .arvalid (l_axi_arvalid),
    .arready (l_axi_arready),
    .rid     ('0),
    .rdata   (l_axi_rdata),
    .rresp   (l_axi_rresp),
    .rlast   (1'b1),
    .rvalid  (l_axi_rvalid),
    .rready  (l_axi_rready)
  );
`endif

`ifdef UVM
  // ------------------------------------------------------------------
  // SV-UVM harness (`--dut ocah_axi_vip --framework uvm`): clock/reset,
  // the one ocah_axi_if the VIP master, fault slave, and passive monitor
  // all attach to, config_db publication, and run_test(). Compiled only
  // when the native-uvm flow defines UVM; the cocotb flow sees only the
  // passive nets above.
  // ------------------------------------------------------------------
  import uvm_pkg::*;

  // 100 MHz bus clock; reset released after 10 cycles.
  initial clk = 1'b0;
  always #5ns clk = ~clk;

  initial begin
    rst_n = 1'b0;
    repeat (10) @(posedge clk);
    rst_n = 1'b1;
  end

  // One interface instance carries the whole selftest bus: the master
  // driver procedurally drives the initiator-side signals, the slave
  // driver the responder-side signals, and the passive monitor samples
  // both through mon_cb (no DUT in the loop; the s_axi/t_axi flat nets
  // above belong to the cocotb shape and stay idle here).
  ocah_axi_if u_axi_if (
    .aclk(clk),
    .aresetn(rst_n)
  );

  // Struct-port bundle: the VIP master drives u_mt_master_if, whose members
  // feed the flat mt_axi request nets and take the response nets back, so the
  // struct pack above serves both shapes; the slave agent answers on
  // u_mt_axi_if behind the bridge. The interface members are the default
  // 64/64/16/16 geometry; the assigns keep the 32-bit, 8-bit-ID, 1-bit-user
  // geometry the struct is typed at.
  ocah_axi_if u_mt_master_if (
    .aclk(clk),
    .aresetn(rst_n)
  );

  assign mt_axi_awid     = u_mt_master_if.awid[7:0];
  assign mt_axi_awaddr   = u_mt_master_if.awaddr[31:0];
  assign mt_axi_awlen    = u_mt_master_if.awlen;
  assign mt_axi_awsize   = u_mt_master_if.awsize;
  assign mt_axi_awburst  = u_mt_master_if.awburst;
  assign mt_axi_awlock   = u_mt_master_if.awlock;
  assign mt_axi_awcache  = u_mt_master_if.awcache;
  assign mt_axi_awprot   = u_mt_master_if.awprot;
  assign mt_axi_awqos    = u_mt_master_if.awqos;
  assign mt_axi_awregion = u_mt_master_if.awregion;
  assign mt_axi_awuser   = u_mt_master_if.awuser[0];
  assign mt_axi_awvalid  = u_mt_master_if.awvalid;
  assign mt_axi_wdata    = u_mt_master_if.wdata[31:0];
  assign mt_axi_wstrb    = u_mt_master_if.wstrb[3:0];
  assign mt_axi_wlast    = u_mt_master_if.wlast;
  assign mt_axi_wuser    = u_mt_master_if.wuser[0];
  assign mt_axi_wvalid   = u_mt_master_if.wvalid;
  assign mt_axi_bready   = u_mt_master_if.bready;
  assign mt_axi_arid     = u_mt_master_if.arid[7:0];
  assign mt_axi_araddr   = u_mt_master_if.araddr[31:0];
  assign mt_axi_arlen    = u_mt_master_if.arlen;
  assign mt_axi_arsize   = u_mt_master_if.arsize;
  assign mt_axi_arburst  = u_mt_master_if.arburst;
  assign mt_axi_arlock   = u_mt_master_if.arlock;
  assign mt_axi_arcache  = u_mt_master_if.arcache;
  assign mt_axi_arprot   = u_mt_master_if.arprot;
  assign mt_axi_arqos    = u_mt_master_if.arqos;
  assign mt_axi_arregion = u_mt_master_if.arregion;
  assign mt_axi_aruser   = u_mt_master_if.aruser[0];
  assign mt_axi_arvalid  = u_mt_master_if.arvalid;
  assign mt_axi_rready   = u_mt_master_if.rready;

  assign u_mt_master_if.awready = mt_axi_awready;
  assign u_mt_master_if.wready  = mt_axi_wready;
  assign u_mt_master_if.bid     = 16'(mt_axi_bid);
  assign u_mt_master_if.bresp   = mt_axi_bresp;
  assign u_mt_master_if.buser   = 16'(mt_axi_buser);
  assign u_mt_master_if.bvalid  = mt_axi_bvalid;
  assign u_mt_master_if.arready = mt_axi_arready;
  assign u_mt_master_if.rid     = 16'(mt_axi_rid);
  assign u_mt_master_if.rdata   = 64'(mt_axi_rdata);
  assign u_mt_master_if.rresp   = mt_axi_rresp;
  assign u_mt_master_if.rlast   = mt_axi_rlast;
  assign u_mt_master_if.ruser   = 16'(mt_axi_ruser);
  assign u_mt_master_if.rvalid  = mt_axi_rvalid;

  // Covergroup sampler shared by the passive envs of both buses: the
  // ocah_axi_cov subscribers each env builds under cfg.en_cov sample every
  // completed transaction into this one instance.
  ocah_axi_cov_if u_axi_cov_if (
    .clk_i (clk),
    .rst_ni(rst_n)
  );

  `include "ocah_axi_vip_tests.sv"

  initial begin
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "axi_vif", u_axi_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "mt_master_vif", u_mt_master_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "mt_axi_vif", u_mt_axi_if);
    uvm_config_db#(virtual ocah_axi_cov_if)::set(null, "*", "axi_cov_vif", u_axi_cov_if);
    run_test();
  end
`endif

endmodule
