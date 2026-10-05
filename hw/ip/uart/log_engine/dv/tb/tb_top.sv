// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Log Engine IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly. Three AXI4-Lite ports are exposed
// flattened for the shared AXI VIP: the CSR port (axil_*, driven by the VIP
// master), the 64-bit log-fetch master port (log_fetch_*, answered by a VIP
// memory responder) and the 32-bit log-write master port (log_write_*,
// answered by a VIP responder and observed by a VIP monitor). The adapters
// below repack the flattened pins into the pulp-platform req/resp structs the
// DUT uses. Clock and reset are driven from cocotb.

`timescale 1ns / 1ps

module log_engine_tb_top
  import log_engine_pkg::*;
#(
  parameter int unsigned FIFO_DEPTH = 4
) (
  input  wire                             clk,
  input  wire                             rst_n,

  // AXI4-Lite register port (flattened, VIP master side)
  input  wire                             axil_awvalid,
  input  wire [31:0]                      axil_awaddr,
  input  wire [2:0]                       axil_awprot,
  output wire                             axil_awready,

  input  wire                             axil_wvalid,
  input  wire [31:0]                      axil_wdata,
  input  wire [3:0]                       axil_wstrb,
  output wire                             axil_wready,

  input  wire                             axil_bready,
  output wire                             axil_bvalid,
  output wire [1:0]                       axil_bresp,

  input  wire                             axil_arvalid,
  input  wire [31:0]                      axil_araddr,
  input  wire [2:0]                       axil_arprot,
  output wire                             axil_arready,

  input  wire                             axil_rready,
  output wire                             axil_rvalid,
  output wire [31:0]                      axil_rdata,
  output wire [1:0]                       axil_rresp,

  // AXI4-Lite log-fetch master port (flattened, VIP responder side)
  output wire                             log_fetch_awvalid,
  output wire [LogFetchAddrWidth-1:0]     log_fetch_awaddr,
  output wire [2:0]                       log_fetch_awprot,
  input  wire                             log_fetch_awready,

  output wire                             log_fetch_wvalid,
  output wire [LogFetchDataWidth-1:0]     log_fetch_wdata,
  output wire [LogFetchStrbWidth-1:0]     log_fetch_wstrb,
  input  wire                             log_fetch_wready,

  output wire                             log_fetch_bready,
  input  wire                             log_fetch_bvalid,
  input  wire [1:0]                       log_fetch_bresp,

  output wire                             log_fetch_arvalid,
  output wire [LogFetchAddrWidth-1:0]     log_fetch_araddr,
  output wire [2:0]                       log_fetch_arprot,
  input  wire                             log_fetch_arready,

  output wire                             log_fetch_rready,
  input  wire                             log_fetch_rvalid,
  input  wire [LogFetchDataWidth-1:0]     log_fetch_rdata,
  input  wire [1:0]                       log_fetch_rresp,

  // AXI4-Lite log-write master port (flattened, VIP responder side)
  output wire                             log_write_awvalid,
  output wire [LogWriteAddrWidth-1:0]     log_write_awaddr,
  output wire [2:0]                       log_write_awprot,
  input  wire                             log_write_awready,

  output wire                             log_write_wvalid,
  output wire [LogWriteDataWidth-1:0]     log_write_wdata,
  output wire [LogWriteStrbWidth-1:0]     log_write_wstrb,
  input  wire                             log_write_wready,

  output wire                             log_write_bready,
  input  wire                             log_write_bvalid,
  input  wire [1:0]                       log_write_bresp,

  output wire                             log_write_arvalid,
  output wire [LogWriteAddrWidth-1:0]     log_write_araddr,
  output wire [2:0]                       log_write_arprot,
  input  wire                             log_write_arready,

  output wire                             log_write_rready,
  input  wire                             log_write_rvalid,
  input  wire [LogWriteDataWidth-1:0]     log_write_rdata,
  input  wire [1:0]                       log_write_rresp,

  // UART transmit-ready pacing input and interrupt output
  input  wire                             uart_tx_ready,
  output wire                             irq
);

  csr_axil_req_t  csr_axil_req;
  csr_axil_resp_t csr_axil_resp;

  assign csr_axil_req.aw_valid = axil_awvalid;
  assign csr_axil_req.aw.addr  = axil_awaddr[RegAddrWidth-1:0];
  assign csr_axil_req.aw.prot  = axil_awprot;
  assign axil_awready          = csr_axil_resp.aw_ready;

  assign csr_axil_req.w_valid  = axil_wvalid;
  assign csr_axil_req.w.data   = axil_wdata;
  assign csr_axil_req.w.strb   = axil_wstrb;
  assign axil_wready           = csr_axil_resp.w_ready;

  assign csr_axil_req.b_ready  = axil_bready;
  assign axil_bvalid           = csr_axil_resp.b_valid;
  assign axil_bresp            = csr_axil_resp.b.resp;

  assign csr_axil_req.ar_valid = axil_arvalid;
  assign csr_axil_req.ar.addr  = axil_araddr[RegAddrWidth-1:0];
  assign csr_axil_req.ar.prot  = axil_arprot;
  assign axil_arready          = csr_axil_resp.ar_ready;

  assign csr_axil_req.r_ready  = axil_rready;
  assign axil_rvalid           = csr_axil_resp.r_valid;
  assign axil_rdata            = csr_axil_resp.r.data;
  assign axil_rresp            = csr_axil_resp.r.resp;

  log_fetch_axil_req_t  log_fetch_axil_req;
  log_fetch_axil_resp_t log_fetch_axil_resp;

  assign log_fetch_awvalid             = log_fetch_axil_req.aw_valid;
  assign log_fetch_awaddr              = log_fetch_axil_req.aw.addr;
  assign log_fetch_awprot              = log_fetch_axil_req.aw.prot;
  assign log_fetch_axil_resp.aw_ready  = log_fetch_awready;

  assign log_fetch_wvalid              = log_fetch_axil_req.w_valid;
  assign log_fetch_wdata               = log_fetch_axil_req.w.data;
  assign log_fetch_wstrb               = log_fetch_axil_req.w.strb;
  assign log_fetch_axil_resp.w_ready   = log_fetch_wready;

  assign log_fetch_bready              = log_fetch_axil_req.b_ready;
  assign log_fetch_axil_resp.b_valid   = log_fetch_bvalid;
  assign log_fetch_axil_resp.b.resp    = log_fetch_bresp;

  assign log_fetch_arvalid             = log_fetch_axil_req.ar_valid;
  assign log_fetch_araddr              = log_fetch_axil_req.ar.addr;
  assign log_fetch_arprot              = log_fetch_axil_req.ar.prot;
  assign log_fetch_axil_resp.ar_ready  = log_fetch_arready;

  assign log_fetch_rready              = log_fetch_axil_req.r_ready;
  assign log_fetch_axil_resp.r_valid   = log_fetch_rvalid;
  assign log_fetch_axil_resp.r.data    = log_fetch_rdata;
  assign log_fetch_axil_resp.r.resp    = log_fetch_rresp;

  log_write_axil_req_t  log_write_axil_req;
  log_write_axil_resp_t log_write_axil_resp;

  assign log_write_awvalid             = log_write_axil_req.aw_valid;
  assign log_write_awaddr              = log_write_axil_req.aw.addr;
  assign log_write_awprot              = log_write_axil_req.aw.prot;
  assign log_write_axil_resp.aw_ready  = log_write_awready;

  assign log_write_wvalid              = log_write_axil_req.w_valid;
  assign log_write_wdata               = log_write_axil_req.w.data;
  assign log_write_wstrb               = log_write_axil_req.w.strb;
  assign log_write_axil_resp.w_ready   = log_write_wready;

  assign log_write_bready              = log_write_axil_req.b_ready;
  assign log_write_axil_resp.b_valid   = log_write_bvalid;
  assign log_write_axil_resp.b.resp    = log_write_bresp;

  assign log_write_arvalid             = log_write_axil_req.ar_valid;
  assign log_write_araddr              = log_write_axil_req.ar.addr;
  assign log_write_arprot              = log_write_axil_req.ar.prot;
  assign log_write_axil_resp.ar_ready  = log_write_arready;

  assign log_write_rready              = log_write_axil_req.r_ready;
  assign log_write_axil_resp.r_valid   = log_write_rvalid;
  assign log_write_axil_resp.r.data    = log_write_rdata;
  assign log_write_axil_resp.r.resp    = log_write_rresp;

  log_engine #(
    .FIFO_DEPTH(FIFO_DEPTH)
  ) u_dut (
    .clk_i                 (clk),
    .rst_ni                (rst_n),

    .csr_axil_req_i        (csr_axil_req),
    .csr_axil_resp_o       (csr_axil_resp),

    .log_fetch_axil_req_o  (log_fetch_axil_req),
    .log_fetch_axil_resp_i (log_fetch_axil_resp),

    .log_write_axil_req_o  (log_write_axil_req),
    .log_write_axil_resp_i (log_write_axil_resp),

    .uart_tx_ready_i       (uart_tx_ready),

    .irq_o                 (irq)
  );

endmodule : log_engine_tb_top
