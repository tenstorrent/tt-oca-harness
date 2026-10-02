// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Buffer a TL-UL link with synchronous request and response FIFOs.
//
// Instantiate separate request and response FIFOs to add elasticity on a TL-UL bus. The
// response FIFO stores d_data as zero for any opcode other than ACCESS_ACK_DATA.
// REQ_PASS and RSP_PASS allow fall-through when the corresponding FIFO is empty. SPARE_REQ_W
// and SPARE_RSP_W carry optional sideband bits alongside each channel.

module tlul_fifo_sync #(
  parameter bit          REQ_PASS = 1'b1,    // Allow A-channel fall-through when empty.
  parameter bit          RSP_PASS = 1'b1,    // Allow D-channel fall-through when empty.
  parameter int unsigned REQ_DEPTH = 2,      // Depth of the host-to-device request FIFO;
                                             // 0 bypasses it and requires REQ_PASS.
  parameter int unsigned RSP_DEPTH = 2,      // Depth of the device-to-host response FIFO;
                                             // 0 bypasses it and requires RSP_PASS.
  parameter int unsigned SPARE_REQ_W = 1,    // Width of spare bits with each request.
  parameter int unsigned SPARE_RSP_W = 1     // Width of spare bits with each response.
) (
  input                     clk_i,        // System clock.
  input                     rst_ni,       // Active-low reset.
  input  tlul_pkg::tl_h2d_t tl_h_i,       // Host-side TL-UL request.
  output tlul_pkg::tl_d2h_t tl_h_o,       // Host-side TL-UL response.
  output tlul_pkg::tl_h2d_t tl_d_o,       // Device-side TL-UL request.
  input  tlul_pkg::tl_d2h_t tl_d_i,       // Device-side TL-UL response.
  input  [SPARE_REQ_W-1:0]  spare_req_i,  // Spare request bits entering with tl_h_i.
  output [SPARE_REQ_W-1:0]  spare_req_o,  // Spare request bits leaving with tl_d_o.
  input  [SPARE_RSP_W-1:0]  spare_rsp_i,  // Spare response bits entering with tl_d_i.
  output [SPARE_RSP_W-1:0]  spare_rsp_o   // Spare response bits leaving with tl_h_o.
);
  // Put everything on the request side into one FIFO
  localparam int unsigned ReqFifoWidth = $bits(tlul_pkg::tl_h2d_t) - 2 + SPARE_REQ_W;

  prim_fifo_sync #(
    .Width(ReqFifoWidth),
    .Pass(REQ_PASS),
    .Depth(REQ_DEPTH)
  ) u_reqfifo (
    .clk_i,
    .rst_ni,
    .clr_i         (1'b0          ),
    .wvalid_i      (tl_h_i.a_valid),
    .wready_o      (tl_h_o.a_ready),
    .wdata_i       ({tl_h_i.a_opcode ,
                     tl_h_i.a_param  ,
                     tl_h_i.a_size   ,
                     tl_h_i.a_source ,
                     tl_h_i.a_address,
                     tl_h_i.a_mask   ,
                     tl_h_i.a_data   ,
                     tl_h_i.a_user   ,
                     spare_req_i}),
    .rvalid_o      (tl_d_o.a_valid),
    .rready_i      (tl_d_i.a_ready),
    .rdata_o       ({tl_d_o.a_opcode ,
                     tl_d_o.a_param  ,
                     tl_d_o.a_size   ,
                     tl_d_o.a_source ,
                     tl_d_o.a_address,
                     tl_d_o.a_mask   ,
                     tl_d_o.a_data   ,
                     tl_d_o.a_user   ,
                     spare_req_o}),
    .full_o        (),
    .depth_o       (),
    .err_o         ()
  );

  // Put everything on the response side into the other FIFO

  localparam int unsigned RspFifoWidth = $bits(tlul_pkg::tl_d2h_t) - 2 + SPARE_RSP_W;

  prim_fifo_sync #(
    .Width(RspFifoWidth),
    .Pass(RSP_PASS),
    .Depth(RSP_DEPTH)
  ) u_rspfifo (
    .clk_i,
    .rst_ni,
    .clr_i         (1'b0          ),
    .wvalid_i      (tl_d_i.d_valid),
    .wready_o      (tl_d_o.d_ready),
    .wdata_i       ({tl_d_i.d_opcode,
                     tl_d_i.d_param ,
                     tl_d_i.d_size  ,
                     tl_d_i.d_source,
                     tl_d_i.d_sink  ,
                     (tl_d_i.d_opcode == tlul_pkg::ACCESS_ACK_DATA) ? tl_d_i.d_data :
                                                                    {top_pkg::TL_DW{1'b0}} ,
                     tl_d_i.d_user  ,
                     tl_d_i.d_error ,
                     spare_rsp_i}),
    .rvalid_o      (tl_h_o.d_valid),
    .rready_i      (tl_h_i.d_ready),
    .rdata_o       ({tl_h_o.d_opcode,
                     tl_h_o.d_param ,
                     tl_h_o.d_size  ,
                     tl_h_o.d_source,
                     tl_h_o.d_sink  ,
                     tl_h_o.d_data  ,
                     tl_h_o.d_user  ,
                     tl_h_o.d_error ,
                     spare_rsp_o}),
    .full_o        (),
    .depth_o       (),
    .err_o         ()
  );

endmodule
