// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Pass an AXI port through while forcing AW, AR, and W user fields to AxiUserOverride.
//
// Wire every other channel field straight across; the module is purely combinational.
// Pass response user fields through unchanged.
// AxiUserWidth must cover the override value; wider values are truncated.
// prim_axi_user_override_struct provides the same function on request and response
// structs and checks the struct field widths with simulation assertions at time zero.

module prim_axi_user_override #(
  parameter  int unsigned AxiAddrWidth = 64,  // AXI address width.
  parameter  int unsigned AxiDataWidth = 64,  // Width of W and R data on both ports; sets the
                                              // strobe width.
  parameter  int unsigned AxiIdWidth   = 1,  // Width of the AW, AR, B and R IDs, identical on both
                                             // ports.
  parameter  int unsigned AxiUserWidth = 1,  // Width of every user field on both ports; must hold
                                             // AxiUserOverride.

  parameter  int unsigned AxiUserOverride = 0,  // Constant written onto outbound AW/AR/W user
                                                // fields.

  localparam int unsigned AxiStrbWidth = AxiDataWidth / 8,  // Write-strobe width from AxiDataWidth.

  localparam type addr_t  = logic [AxiAddrWidth-1:0],  // Address type alias.
  localparam type data_t  = logic [AxiDataWidth-1:0],  // Data type alias.
  localparam type id_t    = logic [AxiIdWidth-1:0],  // ID type alias.
  localparam type strb_t  = logic [AxiStrbWidth-1:0],  // Strobe type alias.
  localparam type user_t  = logic [AxiUserWidth-1:0]  // User type alias.
) (
  input  logic             axi_in_awvalid_i,  // Forwarded unchanged to axi_out_awvalid_o.
  input  id_t              axi_in_awid_i,  // Forwarded unchanged to axi_out_awid_o.
  input  addr_t            axi_in_awaddr_i,  // Forwarded unchanged to axi_out_awaddr_o.
  input  axi_pkg::len_t    axi_in_awlen_i,  // Forwarded unchanged to axi_out_awlen_o.
  input  axi_pkg::size_t   axi_in_awsize_i,  // Forwarded unchanged to axi_out_awsize_o.
  input  axi_pkg::burst_t  axi_in_awburst_i,  // Forwarded unchanged to axi_out_awburst_o.
  input  logic             axi_in_awlock_i,  // Forwarded unchanged to axi_out_awlock_o.
  input  axi_pkg::cache_t  axi_in_awcache_i,  // Forwarded unchanged to axi_out_awcache_o.
  input  axi_pkg::prot_t   axi_in_awprot_i,  // Forwarded unchanged to axi_out_awprot_o.
  input  axi_pkg::qos_t    axi_in_awqos_i,  // Forwarded unchanged to axi_out_awqos_o.
  input  axi_pkg::region_t axi_in_awregion_i,  // Forwarded unchanged to axi_out_awregion_o.
  input  axi_pkg::atop_t   axi_in_awatop_i,  // Forwarded unchanged to axi_out_awatop_o.
  input  user_t            axi_in_awuser_i,  // Not used; axi_out_awuser_o carries AxiUserOverride
                                             // instead.
  output logic             axi_in_awready_o,  // Driven unchanged from axi_out_awready_i.
  input  logic             axi_in_wvalid_i,  // Forwarded unchanged to axi_out_wvalid_o.
  input  data_t            axi_in_wdata_i,  // Forwarded unchanged to axi_out_wdata_o.
  input  strb_t            axi_in_wstrb_i,  // Forwarded unchanged to axi_out_wstrb_o.
  input  logic             axi_in_wlast_i,  // Forwarded unchanged to axi_out_wlast_o.
  input  user_t            axi_in_wuser_i,  // Not used; axi_out_wuser_o carries AxiUserOverride
                                            // instead.
  output logic             axi_in_wready_o,  // Driven unchanged from axi_out_wready_i.
  output logic             axi_in_bvalid_o,  // Driven unchanged from axi_out_bvalid_i.
  output id_t              axi_in_bid_o,  // Driven unchanged from axi_out_bid_i.
  output axi_pkg::resp_t   axi_in_bresp_o,  // Driven unchanged from axi_out_bresp_i.
  output user_t            axi_in_buser_o,  // Driven unchanged from axi_out_buser_i.
  input  logic             axi_in_bready_i,  // Forwarded unchanged to axi_out_bready_o.
  input  logic             axi_in_arvalid_i,  // Forwarded unchanged to axi_out_arvalid_o.
  input  id_t              axi_in_arid_i,  // Forwarded unchanged to axi_out_arid_o.
  input  addr_t            axi_in_araddr_i,  // Forwarded unchanged to axi_out_araddr_o.
  input  axi_pkg::len_t    axi_in_arlen_i,  // Forwarded unchanged to axi_out_arlen_o.
  input  axi_pkg::size_t   axi_in_arsize_i,  // Forwarded unchanged to axi_out_arsize_o.
  input  axi_pkg::burst_t  axi_in_arburst_i,  // Forwarded unchanged to axi_out_arburst_o.
  input  logic             axi_in_arlock_i,  // Forwarded unchanged to axi_out_arlock_o.
  input  axi_pkg::cache_t  axi_in_arcache_i,  // Forwarded unchanged to axi_out_arcache_o.
  input  axi_pkg::prot_t   axi_in_arprot_i,  // Forwarded unchanged to axi_out_arprot_o.
  input  axi_pkg::qos_t    axi_in_arqos_i,  // Forwarded unchanged to axi_out_arqos_o.
  input  axi_pkg::region_t axi_in_arregion_i,  // Forwarded unchanged to axi_out_arregion_o.
  input  user_t            axi_in_aruser_i,  // Not used; axi_out_aruser_o carries AxiUserOverride
                                             // instead.
  output logic             axi_in_arready_o,  // Driven unchanged from axi_out_arready_i.
  output logic             axi_in_rvalid_o,  // Driven unchanged from axi_out_rvalid_i.
  output id_t              axi_in_rid_o,  // Driven unchanged from axi_out_rid_i.
  output data_t            axi_in_rdata_o,  // Driven unchanged from axi_out_rdata_i.
  output axi_pkg::resp_t   axi_in_rresp_o,  // Driven unchanged from axi_out_rresp_i.
  output logic             axi_in_rlast_o,  // Driven unchanged from axi_out_rlast_i.
  output user_t            axi_in_ruser_o,  // Driven unchanged from axi_out_ruser_i.
  input  logic             axi_in_rready_i,  // Forwarded unchanged to axi_out_rready_o.

  output logic             axi_out_awvalid_o,  // Driven unchanged from axi_in_awvalid_i.
  output id_t              axi_out_awid_o,  // Driven unchanged from axi_in_awid_i.
  output addr_t            axi_out_awaddr_o,  // Driven unchanged from axi_in_awaddr_i.
  output axi_pkg::len_t    axi_out_awlen_o,  // Driven unchanged from axi_in_awlen_i.
  output axi_pkg::size_t   axi_out_awsize_o,  // Driven unchanged from axi_in_awsize_i.
  output axi_pkg::burst_t  axi_out_awburst_o,  // Driven unchanged from axi_in_awburst_i.
  output logic             axi_out_awlock_o,  // Driven unchanged from axi_in_awlock_i.
  output axi_pkg::cache_t  axi_out_awcache_o,  // Driven unchanged from axi_in_awcache_i.
  output axi_pkg::prot_t   axi_out_awprot_o,  // Driven unchanged from axi_in_awprot_i.
  output axi_pkg::qos_t    axi_out_awqos_o,  // Driven unchanged from axi_in_awqos_i.
  output axi_pkg::region_t axi_out_awregion_o,  // Driven unchanged from axi_in_awregion_i.
  output axi_pkg::atop_t   axi_out_awatop_o,  // Driven unchanged from axi_in_awatop_i.
  output user_t            axi_out_awuser_o,  // Driven with AxiUserOverride in place of
                                              // axi_in_awuser_i.
  input  logic             axi_out_awready_i,  // Forwarded unchanged to axi_in_awready_o.
  output logic             axi_out_wvalid_o,  // Driven unchanged from axi_in_wvalid_i.
  output data_t            axi_out_wdata_o,  // Driven unchanged from axi_in_wdata_i.
  output strb_t            axi_out_wstrb_o,  // Driven unchanged from axi_in_wstrb_i.
  output logic             axi_out_wlast_o,  // Driven unchanged from axi_in_wlast_i.
  output user_t            axi_out_wuser_o,  // Driven with AxiUserOverride in place of
                                             // axi_in_wuser_i.
  input  logic             axi_out_wready_i,  // Forwarded unchanged to axi_in_wready_o.
  input  logic             axi_out_bvalid_i,  // Forwarded unchanged to axi_in_bvalid_o.
  input  id_t              axi_out_bid_i,  // Forwarded unchanged to axi_in_bid_o.
  input  axi_pkg::resp_t   axi_out_bresp_i,  // Forwarded unchanged to axi_in_bresp_o.
  input  user_t            axi_out_buser_i,  // Forwarded unchanged to axi_in_buser_o.
  output logic             axi_out_bready_o,  // Driven unchanged from axi_in_bready_i.
  output logic             axi_out_arvalid_o,  // Driven unchanged from axi_in_arvalid_i.
  output id_t              axi_out_arid_o,  // Driven unchanged from axi_in_arid_i.
  output addr_t            axi_out_araddr_o,  // Driven unchanged from axi_in_araddr_i.
  output axi_pkg::len_t    axi_out_arlen_o,  // Driven unchanged from axi_in_arlen_i.
  output axi_pkg::size_t   axi_out_arsize_o,  // Driven unchanged from axi_in_arsize_i.
  output axi_pkg::burst_t  axi_out_arburst_o,  // Driven unchanged from axi_in_arburst_i.
  output logic             axi_out_arlock_o,  // Driven unchanged from axi_in_arlock_i.
  output axi_pkg::cache_t  axi_out_arcache_o,  // Driven unchanged from axi_in_arcache_i.
  output axi_pkg::prot_t   axi_out_arprot_o,  // Driven unchanged from axi_in_arprot_i.
  output axi_pkg::qos_t    axi_out_arqos_o,  // Driven unchanged from axi_in_arqos_i.
  output axi_pkg::region_t axi_out_arregion_o,  // Driven unchanged from axi_in_arregion_i.
  output user_t            axi_out_aruser_o,  // Driven with AxiUserOverride in place of
                                              // axi_in_aruser_i.
  input  logic             axi_out_arready_i,  // Forwarded unchanged to axi_in_arready_o.
  input  logic             axi_out_rvalid_i,  // Forwarded unchanged to axi_in_rvalid_o.
  input  id_t              axi_out_rid_i,  // Forwarded unchanged to axi_in_rid_o.
  input  data_t            axi_out_rdata_i,  // Forwarded unchanged to axi_in_rdata_o.
  input  axi_pkg::resp_t   axi_out_rresp_i,  // Forwarded unchanged to axi_in_rresp_o.
  input  logic             axi_out_rlast_i,  // Forwarded unchanged to axi_in_rlast_o.
  input  user_t            axi_out_ruser_i,  // Forwarded unchanged to axi_in_ruser_o.
  output logic             axi_out_rready_o  // Driven unchanged from axi_in_rready_i.
);

  assign axi_out_awvalid_o  = axi_in_awvalid_i;
  assign axi_out_awid_o     = axi_in_awid_i;
  assign axi_out_awaddr_o   = axi_in_awaddr_i;
  assign axi_out_awatop_o   = axi_in_awatop_i;
  assign axi_out_awregion_o = axi_in_awregion_i;
  assign axi_out_awlen_o    = axi_in_awlen_i;
  assign axi_out_awsize_o   = axi_in_awsize_i;
  assign axi_out_awburst_o  = axi_in_awburst_i;
  assign axi_out_awlock_o   = axi_in_awlock_i;
  assign axi_out_awcache_o  = axi_in_awcache_i;
  assign axi_out_awprot_o   = axi_in_awprot_i;
  assign axi_out_awqos_o    = axi_in_awqos_i;
  assign axi_out_wvalid_o   = axi_in_wvalid_i;
  assign axi_out_wdata_o    = axi_in_wdata_i;
  assign axi_out_wstrb_o    = axi_in_wstrb_i;
  assign axi_out_wlast_o    = axi_in_wlast_i;
  assign axi_out_bready_o   = axi_in_bready_i;
  assign axi_out_arvalid_o  = axi_in_arvalid_i;
  assign axi_out_arid_o     = axi_in_arid_i;
  assign axi_out_araddr_o   = axi_in_araddr_i;
  assign axi_out_arlen_o    = axi_in_arlen_i;
  assign axi_out_arsize_o   = axi_in_arsize_i;
  assign axi_out_arburst_o  = axi_in_arburst_i;
  assign axi_out_arlock_o   = axi_in_arlock_i;
  assign axi_out_arcache_o  = axi_in_arcache_i;
  assign axi_out_arprot_o   = axi_in_arprot_i;
  assign axi_out_arqos_o    = axi_in_arqos_i;
  assign axi_out_arregion_o = axi_in_arregion_i;
  assign axi_out_rready_o   = axi_in_rready_i;

  assign axi_in_awready_o   = axi_out_awready_i;
  assign axi_in_wready_o    = axi_out_wready_i;
  assign axi_in_bvalid_o    = axi_out_bvalid_i;
  assign axi_in_bid_o       = axi_out_bid_i;
  assign axi_in_bresp_o     = axi_out_bresp_i;
  assign axi_in_buser_o     = axi_out_buser_i;
  assign axi_in_arready_o   = axi_out_arready_i;
  assign axi_in_rvalid_o    = axi_out_rvalid_i;
  assign axi_in_rid_o       = axi_out_rid_i;
  assign axi_in_rdata_o     = axi_out_rdata_i;
  assign axi_in_rresp_o     = axi_out_rresp_i;
  assign axi_in_rlast_o     = axi_out_rlast_i;
  assign axi_in_ruser_o     = axi_out_ruser_i;

  assign axi_out_awuser_o   = user_t'(AxiUserOverride);
  assign axi_out_wuser_o    = user_t'(AxiUserOverride);
  assign axi_out_aruser_o   = user_t'(AxiUserOverride);

endmodule

module prim_axi_user_override_struct #(
  parameter  int unsigned AxiAddrWidth = 64,  // Width of the AW and AR addresses, checked against
                                              // the request struct.
  parameter  int unsigned AxiDataWidth = 64,  // Width of W and R data, checked against both
                                              // structs.
  parameter  int unsigned AxiIdWidth   = 1,  // Width of the AW, AR, B and R IDs, checked against
                                             // both structs.
  parameter  int unsigned AxiUserWidth = 1,  // Width of every user field; must hold
                                             // AxiUserOverride.

  parameter  int unsigned AxiUserOverride = 0,  // Constant driven onto the outbound AW, AR and W
                                                // user fields.

  localparam int unsigned AxiStrbWidth = AxiDataWidth / 8,  // Expected W strobe width, one bit per
                                                            // data byte.

  parameter type axi_req_t = logic,  // AXI request struct shared by the inbound and outbound ports.
  parameter type axi_resp_t = logic,  // AXI response struct shared by the inbound and outbound
                                      // ports.
  localparam type user_t = logic [AxiUserWidth-1:0]  // Cast type for the override value.
) (
  input axi_req_t axi_in_req_i,  // Upstream AXI request whose AW, AR and W user fields are
                                 // replaced.
  output axi_resp_t axi_in_resp_o,  // Upstream AXI response, passed through unchanged.
  output axi_req_t axi_out_req_o,  // Downstream AXI request carrying AxiUserOverride in its request
                                   // user fields.
  input axi_resp_t axi_out_resp_i  // Downstream AXI response, including B and R user fields.
);

  assign axi_out_req_o.aw_valid  = axi_in_req_i.aw_valid;
  assign axi_out_req_o.aw.id     = axi_in_req_i.aw.id;
  assign axi_out_req_o.aw.addr   = axi_in_req_i.aw.addr;
  assign axi_out_req_o.aw.atop   = axi_in_req_i.aw.atop;
  assign axi_out_req_o.aw.region = axi_in_req_i.aw.region;
  assign axi_out_req_o.aw.len    = axi_in_req_i.aw.len;
  assign axi_out_req_o.aw.size   = axi_in_req_i.aw.size;
  assign axi_out_req_o.aw.burst  = axi_in_req_i.aw.burst;
  assign axi_out_req_o.aw.lock   = axi_in_req_i.aw.lock;
  assign axi_out_req_o.aw.cache  = axi_in_req_i.aw.cache;
  assign axi_out_req_o.aw.prot   = axi_in_req_i.aw.prot;
  assign axi_out_req_o.aw.qos    = axi_in_req_i.aw.qos;
  assign axi_out_req_o.w_valid   = axi_in_req_i.w_valid;
  assign axi_out_req_o.w.data    = axi_in_req_i.w.data;
  assign axi_out_req_o.w.strb    = axi_in_req_i.w.strb;
  assign axi_out_req_o.w.last    = axi_in_req_i.w.last;
  assign axi_out_req_o.b_ready   = axi_in_req_i.b_ready;
  assign axi_out_req_o.ar_valid  = axi_in_req_i.ar_valid;
  assign axi_out_req_o.ar.id     = axi_in_req_i.ar.id;
  assign axi_out_req_o.ar.addr   = axi_in_req_i.ar.addr;
  assign axi_out_req_o.ar.len    = axi_in_req_i.ar.len;
  assign axi_out_req_o.ar.size   = axi_in_req_i.ar.size;
  assign axi_out_req_o.ar.burst  = axi_in_req_i.ar.burst;
  assign axi_out_req_o.ar.lock   = axi_in_req_i.ar.lock;
  assign axi_out_req_o.ar.cache  = axi_in_req_i.ar.cache;
  assign axi_out_req_o.ar.prot   = axi_in_req_i.ar.prot;
  assign axi_out_req_o.ar.qos    = axi_in_req_i.ar.qos;
  assign axi_out_req_o.ar.region = axi_in_req_i.ar.region;
  assign axi_out_req_o.r_ready   = axi_in_req_i.r_ready;

  assign axi_in_resp_o.aw_ready = axi_out_resp_i.aw_ready;
  assign axi_in_resp_o.w_ready  = axi_out_resp_i.w_ready;
  assign axi_in_resp_o.b_valid  = axi_out_resp_i.b_valid;
  assign axi_in_resp_o.b.id     = axi_out_resp_i.b.id;
  assign axi_in_resp_o.b.resp   = axi_out_resp_i.b.resp;
  assign axi_in_resp_o.b.user   = axi_out_resp_i.b.user;
  assign axi_in_resp_o.ar_ready = axi_out_resp_i.ar_ready;
  assign axi_in_resp_o.r_valid  = axi_out_resp_i.r_valid;
  assign axi_in_resp_o.r.id     = axi_out_resp_i.r.id;
  assign axi_in_resp_o.r.data   = axi_out_resp_i.r.data;
  assign axi_in_resp_o.r.resp   = axi_out_resp_i.r.resp;
  assign axi_in_resp_o.r.last   = axi_out_resp_i.r.last;
  assign axi_in_resp_o.r.user   = axi_out_resp_i.r.user;

  assign axi_out_req_o.aw.user   = user_t'(AxiUserOverride);
  assign axi_out_req_o.w.user    = user_t'(AxiUserOverride);
  assign axi_out_req_o.ar.user   = user_t'(AxiUserOverride);

  // Assertions to make sure the structs are correct
  initial begin
    // User fields
    assert ($bits(axi_in_req_i.aw.user) == AxiUserWidth)
    else $error("axi_in_req_i.aw.user is not the correct width");
    assert ($bits(axi_in_req_i.w.user) == AxiUserWidth)
    else $error("axi_in_req_i.w.user is not the correct width");
    assert ($bits(axi_in_req_i.ar.user) == AxiUserWidth)
    else $error("axi_in_req_i.ar.user is not the correct width");
    assert ($bits(axi_out_resp_i.b.user) == AxiUserWidth)
    else $error("axi_out_resp_i.b.user is not the correct width");
    assert ($bits(axi_out_resp_i.r.user) == AxiUserWidth)
    else $error("axi_out_resp_i.r.user is not the correct width");

    // Address fields
    assert ($bits(axi_in_req_i.aw.addr) == AxiAddrWidth)
    else $error("axi_in_req_i.aw.addr is not the correct width");
    assert ($bits(axi_in_req_i.ar.addr) == AxiAddrWidth)
    else $error("axi_in_req_i.ar.addr is not the correct width");

    // Data fields
    assert ($bits(axi_in_req_i.w.data) == AxiDataWidth)
    else $error("axi_in_req_i.w.data is not the correct width");
    assert ($bits(axi_out_resp_i.r.data) == AxiDataWidth)
    else $error("axi_out_resp_i.r.data is not the correct width");

    // ID fields
    assert ($bits(axi_in_req_i.aw.id) == AxiIdWidth)
    else $error("axi_in_req_i.aw.id is not the correct width");
    assert ($bits(axi_in_req_i.ar.id) == AxiIdWidth)
    else $error("axi_in_req_i.ar.id is not the correct width");
    assert ($bits(axi_out_resp_i.b.id) == AxiIdWidth)
    else $error("axi_out_resp_i.b.id is not the correct width");
    assert ($bits(axi_out_resp_i.r.id) == AxiIdWidth)
    else $error("axi_out_resp_i.r.id is not the correct width");

    // Strobe fields
    assert ($bits(axi_in_req_i.w.strb) == AxiStrbWidth)
    else $error("axi_in_req_i.w.strb is not the correct width");

    // Response fields
    assert ($bits(axi_out_resp_i.b.resp) == 2)
    else $error("axi_out_resp_i.b.resp is not the correct width");
    assert ($bits(axi_out_resp_i.r.resp) == 2)
    else $error("axi_out_resp_i.r.resp is not the correct width");

    // Control fields
    assert ($bits(axi_out_resp_i.r.last) == 1)
    else $error("axi_out_resp_i.r.last is not the correct width");
    assert ($bits(axi_in_req_i.w.last) == 1)
    else $error("axi_in_req_i.w.last is not the correct width");

    // AXI protocol fields
    assert ($bits(axi_in_req_i.aw.len) == 8)
    else $error("axi_in_req_i.aw.len is not the correct width");
    assert ($bits(axi_in_req_i.ar.len) == 8)
    else $error("axi_in_req_i.ar.len is not the correct width");
    assert ($bits(axi_in_req_i.aw.size) == 3)
    else $error("axi_in_req_i.aw.size is not the correct width");
    assert ($bits(axi_in_req_i.ar.size) == 3)
    else $error("axi_in_req_i.ar.size is not the correct width");
    assert ($bits(axi_in_req_i.aw.burst) == 2)
    else $error("axi_in_req_i.aw.burst is not the correct width");
    assert ($bits(axi_in_req_i.ar.burst) == 2)
    else $error("axi_in_req_i.ar.burst is not the correct width");
    assert ($bits(axi_in_req_i.aw.lock) == 1)
    else $error("axi_in_req_i.aw.lock is not the correct width");
    assert ($bits(axi_in_req_i.ar.lock) == 1)
    else $error("axi_in_req_i.ar.lock is not the correct width");
    assert ($bits(axi_in_req_i.aw.cache) == 4)
    else $error("axi_in_req_i.aw.cache is not the correct width");
    assert ($bits(axi_in_req_i.ar.cache) == 4)
    else $error("axi_in_req_i.ar.cache is not the correct width");
    assert ($bits(axi_in_req_i.aw.prot) == 3)
    else $error("axi_in_req_i.aw.prot is not the correct width");
    assert ($bits(axi_in_req_i.ar.prot) == 3)
    else $error("axi_in_req_i.ar.prot is not the correct width");
    assert ($bits(axi_in_req_i.aw.qos) == 4)
    else $error("axi_in_req_i.aw.qos is not the correct width");
    assert ($bits(axi_in_req_i.ar.qos) == 4)
    else $error("axi_in_req_i.ar.qos is not the correct width");
    assert ($bits(axi_in_req_i.aw.region) == 4)
    else $error("axi_in_req_i.aw.region is not the correct width");
    assert ($bits(axi_in_req_i.ar.region) == 4)
    else $error("axi_in_req_i.ar.region is not the correct width");
    assert ($bits(axi_in_req_i.aw.atop) == 6)
    else $error("axi_in_req_i.aw.atop is not the correct width");
  end

endmodule
