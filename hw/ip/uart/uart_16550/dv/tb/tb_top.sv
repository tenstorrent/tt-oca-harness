// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// UART 16550 IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly. The shared AXI VIP's AXI4-Lite
// master binds to the flattened axil_* ports via AxiLiteBus.from_prefix(dut,
// "axil"); the adapter below repacks them into the pulp-platform req/resp
// structs the DUT expects and narrows the address to the register map's own
// width. The serial line and the modem pins are exposed for the shared UART
// VIP's line driver and sampler. Clock and reset are driven from cocotb.

`timescale 1ns / 1ps

module uart_16550_tb_top #(
  parameter int unsigned TX_FIFO_DEPTH = 16,
  parameter int unsigned RX_FIFO_DEPTH = 16
) (
  input  wire        clk,
  input  wire        rst_n,

  // AXI4-Lite register port (flattened, VIP master side)
  input  wire        axil_awvalid,
  input  wire [31:0] axil_awaddr,
  input  wire [2:0]  axil_awprot,
  output wire        axil_awready,

  input  wire        axil_wvalid,
  input  wire [31:0] axil_wdata,
  input  wire [3:0]  axil_wstrb,
  output wire        axil_wready,

  input  wire        axil_bready,
  output wire        axil_bvalid,
  output wire [1:0]  axil_bresp,

  input  wire        axil_arvalid,
  input  wire [31:0] axil_araddr,
  input  wire [2:0]  axil_arprot,
  output wire        axil_arready,

  input  wire        axil_rready,
  output wire        axil_rvalid,
  output wire [31:0] axil_rdata,
  output wire [1:0]  axil_rresp,

  // Serial line
  input  wire        rx,
  output wire        tx,

  // Modem inputs and outputs (active low)
  input  wire        cts_n,
  input  wire        dsr_n,
  input  wire        ri_n,
  input  wire        dcd_n,
  output wire        rts_n,
  output wire        dtr_n,
  output wire        out1_n,
  output wire        out2_n,

  // DMA, error and interrupt outputs
  output wire        rxrdy,
  output wire        txrdy,
  output wire        err,
  output wire        irq
);

  uart_16550_pkg::axil_req_t  axil_req;
  uart_16550_pkg::axil_resp_t axil_resp;

  assign axil_req.aw_valid = axil_awvalid;
  assign axil_req.aw.addr  = axil_awaddr[uart_16550_pkg::REG_ADDR_WIDTH-1:0];
  assign axil_req.aw.prot  = axil_awprot;
  assign axil_awready      = axil_resp.aw_ready;

  assign axil_req.w_valid  = axil_wvalid;
  assign axil_req.w.data   = axil_wdata;
  assign axil_req.w.strb   = axil_wstrb;
  assign axil_wready       = axil_resp.w_ready;

  assign axil_req.b_ready  = axil_bready;
  assign axil_bvalid       = axil_resp.b_valid;
  assign axil_bresp        = axil_resp.b.resp;

  assign axil_req.ar_valid = axil_arvalid;
  assign axil_req.ar.addr  = axil_araddr[uart_16550_pkg::REG_ADDR_WIDTH-1:0];
  assign axil_req.ar.prot  = axil_arprot;
  assign axil_arready      = axil_resp.ar_ready;

  assign axil_req.r_ready  = axil_rready;
  assign axil_rvalid       = axil_resp.r_valid;
  assign axil_rdata        = axil_resp.r.data;
  assign axil_rresp        = axil_resp.r.resp;

  uart_16550 #(
    .TX_FIFO_DEPTH (TX_FIFO_DEPTH),
    .RX_FIFO_DEPTH (RX_FIFO_DEPTH)
  ) u_dut (
    .clk_i       (clk),
    .rst_ni      (rst_n),

    .axil_req_i  (axil_req),
    .axil_resp_o (axil_resp),

    .rx_i        (rx),
    .tx_o        (tx),

    .cts_ni      (cts_n),
    .dsr_ni      (dsr_n),
    .ri_ni       (ri_n),
    .dcd_ni      (dcd_n),

    .rts_no      (rts_n),
    .dtr_no      (dtr_n),
    .out1_no     (out1_n),
    .out2_no     (out2_n),

    .rxrdy_o     (rxrdy),
    .txrdy_o     (txrdy),

    .err_o       (err),

    .irq_o       (irq)
  );

endmodule : uart_16550_tb_top
