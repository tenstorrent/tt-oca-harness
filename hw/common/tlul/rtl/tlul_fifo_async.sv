// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Cross a TL-UL link between two clock domains with asynchronous request and response FIFOs.
//
// The A channel crosses from clk_h_i to clk_d_i and the D channel from clk_d_i back to clk_h_i,
// each through a gray-pointer prim_fifo_async, so the two clocks may be unrelated. Every TL-UL
// field crosses unchanged, integrity included. REQ_DEPTH and RSP_DEPTH must be powers of two.

module tlul_fifo_async #(
  parameter int unsigned REQ_DEPTH = 2,  // Depth of the host-to-device request FIFO.
  parameter int unsigned RSP_DEPTH = 2   // Depth of the device-to-host response FIFO.
) (
  input                     clk_h_i,   // Host-side clock.
  input                     rst_h_ni,  // Host-side active-low reset.
  input                     clk_d_i,   // Device-side clock.
  input                     rst_d_ni,  // Device-side active-low reset.
  input  tlul_pkg::tl_h2d_t tl_h_i,    // Host-side TL-UL request, in clk_h_i.
  output tlul_pkg::tl_d2h_t tl_h_o,    // Host-side TL-UL response, in clk_h_i.
  output tlul_pkg::tl_h2d_t tl_d_o,    // Device-side TL-UL request, in clk_d_i.
  input  tlul_pkg::tl_d2h_t tl_d_i     // Device-side TL-UL response, in clk_d_i.
);

  localparam int unsigned ReqFifoWidth = $bits(tlul_pkg::tl_h2d_t) - 2;

  prim_fifo_async #(
    .Width(ReqFifoWidth),
    .Depth(REQ_DEPTH)
  ) u_reqfifo (
    .clk_wr_i  (clk_h_i),
    .rst_wr_ni (rst_h_ni),
    .wvalid_i  (tl_h_i.a_valid),
    .wready_o  (tl_h_o.a_ready),
    .wdata_i   ({tl_h_i.a_opcode ,
                 tl_h_i.a_param  ,
                 tl_h_i.a_size   ,
                 tl_h_i.a_source ,
                 tl_h_i.a_address,
                 tl_h_i.a_mask   ,
                 tl_h_i.a_data   ,
                 tl_h_i.a_user}),
    .wdepth_o  (),
    .clk_rd_i  (clk_d_i),
    .rst_rd_ni (rst_d_ni),
    .rvalid_o  (tl_d_o.a_valid),
    .rready_i  (tl_d_i.a_ready),
    .rdata_o   ({tl_d_o.a_opcode ,
                 tl_d_o.a_param  ,
                 tl_d_o.a_size   ,
                 tl_d_o.a_source ,
                 tl_d_o.a_address,
                 tl_d_o.a_mask   ,
                 tl_d_o.a_data   ,
                 tl_d_o.a_user}),
    .rdepth_o  ()
  );

  localparam int unsigned RspFifoWidth = $bits(tlul_pkg::tl_d2h_t) - 2;

  prim_fifo_async #(
    .Width(RspFifoWidth),
    .Depth(RSP_DEPTH)
  ) u_rspfifo (
    .clk_wr_i  (clk_d_i),
    .rst_wr_ni (rst_d_ni),
    .wvalid_i  (tl_d_i.d_valid),
    .wready_o  (tl_d_o.d_ready),
    .wdata_i   ({tl_d_i.d_opcode,
                 tl_d_i.d_param ,
                 tl_d_i.d_size  ,
                 tl_d_i.d_source,
                 tl_d_i.d_sink  ,
                 tl_d_i.d_data  ,
                 tl_d_i.d_user  ,
                 tl_d_i.d_error}),
    .wdepth_o  (),
    .clk_rd_i  (clk_h_i),
    .rst_rd_ni (rst_h_ni),
    .rvalid_o  (tl_h_o.d_valid),
    .rready_i  (tl_h_i.d_ready),
    .rdata_o   ({tl_h_o.d_opcode,
                 tl_h_o.d_param ,
                 tl_h_o.d_size  ,
                 tl_h_o.d_source,
                 tl_h_o.d_sink  ,
                 tl_h_o.d_data  ,
                 tl_h_o.d_user  ,
                 tl_h_o.d_error}),
    .rdepth_o  ()
  );

endmodule
