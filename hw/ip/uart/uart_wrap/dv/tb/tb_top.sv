// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// UART wrapper IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly. The wrapper's AXI4-Lite CSR port
// is exposed flattened (axil_*) for the shared AXI VIP's master and its
// 64-bit log-fetch master port (log_fetch_*) for the VIP's memory responder;
// the adapters below repack the pins into the pulp-platform req/resp structs
// the DUT uses. Each UART's serial line is exposed as its own scalar pin pair
// (uart_rx_<i>/uart_tx_<i>) so the shared UART VIP's line engines bind to one
// instance each; the remaining per-UART pins stay packed one bit per UART.
// The register-map bases and sizes come from the generated RDL header, the
// same values the SMC integration passes. Clock and reset are driven from
// cocotb.

`timescale 1ns / 1ps

`include "uart_wrap_reg.svh"

module uart_wrap_tb_top #(
  parameter int unsigned UART_TX_FIFO_DEPTH    = 32,
  parameter int unsigned UART_RX_FIFO_DEPTH    = 32,
  parameter int unsigned LOG_ENGINE_FIFO_DEPTH = 4
) (
  input  wire                                             clk,
  input  wire                                             rst_n,

  // AXI4-Lite register port (flattened, VIP master side)
  input  wire                                             axil_awvalid,
  input  wire [31:0]                                      axil_awaddr,
  input  wire [2:0]                                       axil_awprot,
  output wire                                             axil_awready,

  input  wire                                             axil_wvalid,
  input  wire [31:0]                                      axil_wdata,
  input  wire [3:0]                                       axil_wstrb,
  output wire                                             axil_wready,

  input  wire                                             axil_bready,
  output wire                                             axil_bvalid,
  output wire [1:0]                                       axil_bresp,

  input  wire                                             axil_arvalid,
  input  wire [31:0]                                      axil_araddr,
  input  wire [2:0]                                       axil_arprot,
  output wire                                             axil_arready,

  input  wire                                             axil_rready,
  output wire                                             axil_rvalid,
  output wire [31:0]                                      axil_rdata,
  output wire [1:0]                                       axil_rresp,

  // AXI4-Lite log-fetch master port (flattened, VIP responder side)
  output wire                                             log_fetch_awvalid,
  output wire [log_engine_pkg::LOG_FETCH_ADDR_WIDTH-1:0]  log_fetch_awaddr,
  output wire [2:0]                                       log_fetch_awprot,
  input  wire                                             log_fetch_awready,

  output wire                                             log_fetch_wvalid,
  output wire [log_engine_pkg::LOG_FETCH_DATA_WIDTH-1:0]  log_fetch_wdata,
  output wire [log_engine_pkg::LOG_FETCH_STRB_WIDTH-1:0]  log_fetch_wstrb,
  input  wire                                             log_fetch_wready,

  output wire                                             log_fetch_bready,
  input  wire                                             log_fetch_bvalid,
  input  wire [1:0]                                       log_fetch_bresp,

  output wire                                             log_fetch_arvalid,
  output wire [log_engine_pkg::LOG_FETCH_ADDR_WIDTH-1:0]  log_fetch_araddr,
  output wire [2:0]                                       log_fetch_arprot,
  input  wire                                             log_fetch_arready,

  output wire                                             log_fetch_rready,
  input  wire                                             log_fetch_rvalid,
  input  wire [log_engine_pkg::LOG_FETCH_DATA_WIDTH-1:0]  log_fetch_rdata,
  input  wire [1:0]                                       log_fetch_rresp,

  // Pad-mux control, one bit per UART
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_en,

  // Serial lines, one scalar pair per UART
  input  wire                                             uart_rx_0,
  input  wire                                             uart_rx_1,
  input  wire                                             uart_rx_2,
  input  wire                                             uart_rx_3,
  output wire                                             uart_tx_0,
  output wire                                             uart_tx_1,
  output wire                                             uart_tx_2,
  output wire                                             uart_tx_3,

  // Modem inputs and outputs (active low), one bit per UART
  input  wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_cts_n,
  input  wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_dsr_n,
  input  wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_ri_n,
  input  wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_dcd_n,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_rts_n,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_dtr_n,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_out1_n,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_out2_n,

  // DMA, error and interrupt outputs, one bit per UART
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_rxrdy,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_txrdy,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_err,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          uart_irq,
  output wire [uart_wrap_pkg::MAX_NUM_UARTS-1:0]          log_engine_irq
);

  localparam int unsigned NumUarts = uart_wrap_pkg::MAX_NUM_UARTS;

  uart_wrap_pkg::csr_axil_req_t  csr_axil_req;
  uart_wrap_pkg::csr_axil_resp_t csr_axil_resp;

  assign csr_axil_req.aw_valid = axil_awvalid;
  assign csr_axil_req.aw.addr  = axil_awaddr;
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
  assign csr_axil_req.ar.addr  = axil_araddr;
  assign csr_axil_req.ar.prot  = axil_arprot;
  assign axil_arready          = csr_axil_resp.ar_ready;

  assign csr_axil_req.r_ready  = axil_rready;
  assign axil_rvalid           = csr_axil_resp.r_valid;
  assign axil_rdata            = csr_axil_resp.r.data;
  assign axil_rresp            = csr_axil_resp.r.resp;

  log_engine_pkg::log_fetch_axil_req_t  log_fetch_axil_req;
  log_engine_pkg::log_fetch_axil_resp_t log_fetch_axil_resp;

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

  wire [NumUarts-1:0] uart_rx;
  wire [NumUarts-1:0] uart_tx;

  assign uart_rx   = {uart_rx_3, uart_rx_2, uart_rx_1, uart_rx_0};
  assign uart_tx_0 = uart_tx[0];
  assign uart_tx_1 = uart_tx[1];
  assign uart_tx_2 = uart_tx[2];
  assign uart_tx_3 = uart_tx[3];

  uart_wrap #(
    .NUM_UARTS                                 (NumUarts),
    .UART_TX_FIFO_DEPTH                        (UART_TX_FIFO_DEPTH),
    .UART_RX_FIFO_DEPTH                        (UART_RX_FIFO_DEPTH),
    .GEN_LOG_ENGINES                           ({NumUarts{1'b1}}),
    .LOG_ENGINE_FIFO_DEPTH                     (LOG_ENGINE_FIFO_DEPTH),

    .UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR (UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR),
    .UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE      (UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE),
    .UART_LOG_ENGINE_WRAP_SPACING              (uart_wrap_pkg::UART_LOG_ENGINE_WRAP_SPACING),

    .UART_REG_MAP_BASE_ADDR                    (UART_LOG_ENGINE_WRAP_0__UART_REG_MAP_BASE_ADDR),
    .UART_REG_MAP_SIZE                         (UART_LOG_ENGINE_WRAP_0__UART_REG_MAP_SIZE),
    .LOG_ENGINE_REG_MAP_BASE_ADDR (
      UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_REG_MAP_BASE_ADDR
    ),
    .LOG_ENGINE_REG_MAP_SIZE                   (UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_REG_MAP_SIZE),
    .UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR (
      UART_LOG_ENGINE_WRAP_0__UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR
    ),
    .UART_LOG_ENGINE_CTRL_REG_MAP_SIZE (
      UART_LOG_ENGINE_WRAP_0__UART_LOG_ENGINE_CTRL_REG_MAP_SIZE
    )
  ) u_dut (
    .clk_i                 (clk),
    .rst_ni                (rst_n),

    .csr_axil_req_i        (csr_axil_req),
    .csr_axil_resp_o       (csr_axil_resp),

    .log_fetch_axil_req_o  (log_fetch_axil_req),
    .log_fetch_axil_resp_i (log_fetch_axil_resp),

    .uart_en_o             (uart_en),

    .uart_rx_i             (uart_rx),
    .uart_tx_o             (uart_tx),

    .uart_cts_ni           (uart_cts_n),
    .uart_dsr_ni           (uart_dsr_n),
    .uart_ri_ni            (uart_ri_n),
    .uart_dcd_ni           (uart_dcd_n),

    .uart_rts_no           (uart_rts_n),
    .uart_dtr_no           (uart_dtr_n),
    .uart_out1_no          (uart_out1_n),
    .uart_out2_no          (uart_out2_n),

    .uart_rxrdy_o          (uart_rxrdy),
    .uart_txrdy_o          (uart_txrdy),

    .uart_err_o            (uart_err),

    .uart_irq_o            (uart_irq),
    .log_engine_irq_o      (log_engine_irq)
  );

endmodule : uart_wrap_tb_top
