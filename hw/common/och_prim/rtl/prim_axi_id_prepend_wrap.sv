// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// AXI ID Prepend Wrapper
//
//--------------------------------------------------

module prim_axi_id_prepend_wrap #(
  parameter int unsigned AxiInIdWidth  = 6,
  parameter int unsigned AxiOutIdWidth = 8,
  parameter int unsigned AxiDataWidth  = 32,
  parameter int unsigned AxiAddrWidth  = 32,
  parameter int unsigned AxiUserWidth  = 8,

  parameter type axi_in_req_t   = logic,
  parameter type axi_in_resp_t  = logic,
  parameter type axi_out_req_t  = logic,
  parameter type axi_out_resp_t = logic
) (
  input axi_in_req_t axi_in_req_i,
  output axi_in_resp_t axi_in_resp_o,
  output axi_out_req_t axi_out_req_o,
  input axi_out_resp_t axi_out_resp_i
);

  `include "ocah_assert.svh"

  localparam int unsigned IdBuffWidth = AxiOutIdWidth - AxiInIdWidth;

  assign axi_out_req_o.aw_valid   = axi_in_req_i.aw_valid;
  assign axi_out_req_o.aw.id     = {{IdBuffWidth{1'b0}}, axi_in_req_i.aw.id};
  assign axi_out_req_o.aw.addr   = axi_in_req_i.aw.addr;
  assign axi_out_req_o.aw.len    = axi_in_req_i.aw.len;
  assign axi_out_req_o.aw.size   = axi_in_req_i.aw.size;
  assign axi_out_req_o.aw.burst  = axi_in_req_i.aw.burst;
  assign axi_out_req_o.aw.lock   = axi_in_req_i.aw.lock;
  assign axi_out_req_o.aw.cache  = axi_in_req_i.aw.cache;
  assign axi_out_req_o.aw.prot   = axi_in_req_i.aw.prot;
  assign axi_out_req_o.aw.qos    = axi_in_req_i.aw.qos;
  assign axi_out_req_o.aw.region = axi_in_req_i.aw.region;
  assign axi_out_req_o.aw.user   = axi_in_req_i.aw.user;
  assign axi_out_req_o.aw.atop   = axi_in_req_i.aw.atop;
  assign axi_out_req_o.w_valid    = axi_in_req_i.w_valid;
  assign axi_out_req_o.w.data    = axi_in_req_i.w.data;
  assign axi_out_req_o.w.strb    = axi_in_req_i.w.strb;
  assign axi_out_req_o.w.last    = axi_in_req_i.w.last;
  assign axi_out_req_o.w.user    = axi_in_req_i.w.user;
  assign axi_out_req_o.b_ready    = axi_in_req_i.b_ready;
  assign axi_out_req_o.ar_valid   = axi_in_req_i.ar_valid;
  assign axi_out_req_o.ar.id     = {{IdBuffWidth{1'b0}}, axi_in_req_i.ar.id};
  assign axi_out_req_o.ar.addr   = axi_in_req_i.ar.addr;
  assign axi_out_req_o.ar.len    = axi_in_req_i.ar.len;
  assign axi_out_req_o.ar.size   = axi_in_req_i.ar.size;
  assign axi_out_req_o.ar.burst  = axi_in_req_i.ar.burst;
  assign axi_out_req_o.ar.lock   = axi_in_req_i.ar.lock;
  assign axi_out_req_o.ar.cache  = axi_in_req_i.ar.cache;
  assign axi_out_req_o.ar.prot   = axi_in_req_i.ar.prot;
  assign axi_out_req_o.ar.qos    = axi_in_req_i.ar.qos;
  assign axi_out_req_o.ar.region = axi_in_req_i.ar.region;
  assign axi_out_req_o.ar.user   = axi_in_req_i.ar.user;
  assign axi_out_req_o.r_ready    = axi_in_req_i.r_ready;

  assign axi_in_resp_o.aw_ready   = axi_out_resp_i.aw_ready;
  assign axi_in_resp_o.w_ready    = axi_out_resp_i.w_ready;
  assign axi_in_resp_o.b_valid    = axi_out_resp_i.b_valid;
  assign axi_in_resp_o.b.id      = axi_out_resp_i.b.id[AxiInIdWidth-1:0];
  assign axi_in_resp_o.b.resp    = axi_out_resp_i.b.resp;
  assign axi_in_resp_o.b.user    = axi_out_resp_i.b.user;
  assign axi_in_resp_o.ar_ready   = axi_out_resp_i.ar_ready;
  assign axi_in_resp_o.r_valid    = axi_out_resp_i.r_valid;
  assign axi_in_resp_o.r.id      = axi_out_resp_i.r.id[AxiInIdWidth-1:0];
  assign axi_in_resp_o.r.data    = axi_out_resp_i.r.data;
  assign axi_in_resp_o.r.resp    = axi_out_resp_i.r.resp;
  assign axi_in_resp_o.r.user    = axi_out_resp_i.r.user;
  assign axi_in_resp_o.r.last    = axi_out_resp_i.r.last;

  `OCAH_ASSERT_INIT(OutputIDWidthLessThanInputIDWidth, (AxiOutIdWidth >= AxiInIdWidth))

endmodule
