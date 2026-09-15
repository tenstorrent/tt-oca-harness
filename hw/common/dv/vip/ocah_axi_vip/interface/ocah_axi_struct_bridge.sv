// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Struct-port bridge onto the shared AXI interface.
//
// A DUT-mastered AXI4 port carried as pulp-style request/response structs
// (the `AXI_TYPEDEF_*` shapes from axi/typedef.svh) is placed on one
// `ocah_axi_if` instance so the shared slave agent can answer it in either
// realization: the request struct drives the interface's initiator-side
// members, and the responder-side members the agent drives form the response
// struct. The interface carries its default (maximum) geometry, so request
// members are zero-extended and response members truncated to the struct
// widths; the agent's config states the real geometry. The `atop` field of the
// pulp AW channel has no interface member and is not carried.
//
// Simulation collateral; not for synthesis.

module ocah_axi_struct_bridge #(
  parameter type axi_req_t  = logic,
  parameter type axi_resp_t = logic
) (
  input  axi_req_t  axi_req_i,
  output axi_resp_t axi_resp_o,
  ocah_axi_if       axi_if
);

  // Struct member widths come from a constant of the request type: a member
  // select on the port is not a constant expression to every simulator, a
  // select on a parameter is.
  localparam axi_req_t ReqZero = '0;
  localparam int unsigned IdWidth = $bits(ReqZero.aw.id);
  localparam int unsigned UserWidth = $bits(ReqZero.aw.user);
  localparam int unsigned DataWidth = $bits(ReqZero.w.data);
  localparam int unsigned IfIdWidth = $bits(axi_if.awid);
  localparam int unsigned IfAddrWidth = $bits(axi_if.awaddr);
  localparam int unsigned IfUserWidth = $bits(axi_if.awuser);
  localparam int unsigned IfDataWidth = $bits(axi_if.wdata);
  localparam int unsigned IfStrbWidth = $bits(axi_if.wstrb);

  assign axi_if.awid     = IfIdWidth'(axi_req_i.aw.id);
  assign axi_if.awaddr   = IfAddrWidth'(axi_req_i.aw.addr);
  assign axi_if.awlen    = axi_req_i.aw.len;
  assign axi_if.awsize   = axi_req_i.aw.size;
  assign axi_if.awburst  = axi_req_i.aw.burst;
  assign axi_if.awlock   = axi_req_i.aw.lock;
  assign axi_if.awcache  = axi_req_i.aw.cache;
  assign axi_if.awprot   = axi_req_i.aw.prot;
  assign axi_if.awqos    = axi_req_i.aw.qos;
  assign axi_if.awregion = axi_req_i.aw.region;
  assign axi_if.awuser   = IfUserWidth'(axi_req_i.aw.user);
  assign axi_if.awvalid  = axi_req_i.aw_valid;

  assign axi_if.wdata    = IfDataWidth'(axi_req_i.w.data);
  assign axi_if.wstrb    = IfStrbWidth'(axi_req_i.w.strb);
  assign axi_if.wlast    = axi_req_i.w.last;
  assign axi_if.wuser    = IfUserWidth'(axi_req_i.w.user);
  assign axi_if.wvalid   = axi_req_i.w_valid;

  assign axi_if.bready   = axi_req_i.b_ready;

  assign axi_if.arid     = IfIdWidth'(axi_req_i.ar.id);
  assign axi_if.araddr   = IfAddrWidth'(axi_req_i.ar.addr);
  assign axi_if.arlen    = axi_req_i.ar.len;
  assign axi_if.arsize   = axi_req_i.ar.size;
  assign axi_if.arburst  = axi_req_i.ar.burst;
  assign axi_if.arlock   = axi_req_i.ar.lock;
  assign axi_if.arcache  = axi_req_i.ar.cache;
  assign axi_if.arprot   = axi_req_i.ar.prot;
  assign axi_if.arqos    = axi_req_i.ar.qos;
  assign axi_if.arregion = axi_req_i.ar.region;
  assign axi_if.aruser   = IfUserWidth'(axi_req_i.ar.user);
  assign axi_if.arvalid  = axi_req_i.ar_valid;

  assign axi_if.rready   = axi_req_i.r_ready;

  always_comb begin
    axi_resp_o          = '0;
    axi_resp_o.aw_ready = axi_if.awready;
    axi_resp_o.w_ready  = axi_if.wready;
    axi_resp_o.b_valid  = axi_if.bvalid;
    axi_resp_o.b.id     = IdWidth'(axi_if.bid);
    axi_resp_o.b.resp   = axi_if.bresp;
    axi_resp_o.b.user   = UserWidth'(axi_if.buser);
    axi_resp_o.ar_ready = axi_if.arready;
    axi_resp_o.r_valid  = axi_if.rvalid;
    axi_resp_o.r.id     = IdWidth'(axi_if.rid);
    axi_resp_o.r.data   = DataWidth'(axi_if.rdata);
    axi_resp_o.r.resp   = axi_if.rresp;
    axi_resp_o.r.last   = axi_if.rlast;
    axi_resp_o.r.user   = UserWidth'(axi_if.ruser);
  end

endmodule : ocah_axi_struct_bridge
