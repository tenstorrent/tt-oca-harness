// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// UART & Log Engine Wrapper
//
//-----------------------------------------------------------------------------


module uart_log_engine_wrap
  import uart_log_engine_wrap_pkg::*;
#(
  parameter int unsigned UART_TX_FIFO_DEPTH    = 32,
  parameter int unsigned UART_RX_FIFO_DEPTH    = 32,
  parameter bit          GEN_LOG_ENGINE        = 1'b1,
  parameter int unsigned LOG_ENGINE_FIFO_DEPTH = 32,

  parameter bit [REG_ADDR_WIDTH-1:0] UART_REG_MAP_BASE_ADDR = 0,
  parameter bit [REG_ADDR_WIDTH-1:0] UART_REG_MAP_SIZE      = 0,
  parameter bit [REG_ADDR_WIDTH-1:0] LOG_ENGINE_REG_MAP_BASE_ADDR = 0,
  parameter bit [REG_ADDR_WIDTH-1:0] LOG_ENGINE_REG_MAP_SIZE      = 0,
  parameter bit [REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR = 0,
  parameter bit [REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_CTRL_REG_MAP_SIZE = 0
) (
  // Global Interface
  input  logic                                 clk_i,
  input  logic                                 rst_ni,

  // AXI4-Lite Register Interface
  input  csr_axil_req_t                        csr_axil_req_i,
  output csr_axil_resp_t                       csr_axil_resp_o,

  // AXI4-Lite Log fetch Interface
  output log_engine_pkg::log_fetch_axil_req_t  log_fetch_axil_req_o,
  input  log_engine_pkg::log_fetch_axil_resp_t log_fetch_axil_resp_i,

  // Control Interface
  output logic                                 uart_en_o,

  // UART Interface
  input  logic                                 uart_rx_i,
  output logic                                 uart_tx_o,

  // UART Modem Interface
  input  logic                                 uart_cts_ni,
  input  logic                                 uart_dsr_ni,
  input  logic                                 uart_ri_ni,
  input  logic                                 uart_dcd_ni,

  output logic                                 uart_rts_no,
  output logic                                 uart_dtr_no,
  output logic                                 uart_out1_no,
  output logic                                 uart_out2_no,

  // UART DMA Interface
  output logic                                 uart_rxrdy_o,
  output logic                                 uart_txrdy_o,

  // UART Error Interface
  output logic                                 uart_err_o,

  // Interrupt Interface
  output logic                                 uart_irq_o,
  output logic                                 log_engine_irq_o
);

  `include "axi/assign.svh"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  csr_axil_req_t  csr_axil_req;
  csr_axil_resp_t csr_axil_resp;

  csr_axil_req_t  [NUM_REG_MAPS-1:0] csr_axil_reqs;
  csr_axil_resp_t [NUM_REG_MAPS-1:0] csr_axil_resps;

  uart_16550_pkg::axil_req_t  uart_axil_req;
  uart_16550_pkg::axil_resp_t uart_axil_resp;


  //////////////////////////////
  // AXI4-Lite Register Demux //
  //////////////////////////////

  uart_log_engine_wrap_reg_map_e csr_axil_aw_select, csr_axil_ar_select;

  assign csr_axil_req = csr_axil_req_i;
  assign csr_axil_resp_o = csr_axil_resp;

  always_comb begin
    if (csr_axil_req.aw.addr >= UART_REG_MAP_BASE_ADDR &&
            csr_axil_req.aw.addr <  UART_REG_MAP_BASE_ADDR +
                                     UART_REG_MAP_SIZE) begin
      csr_axil_aw_select = UART_REG_MAP;
    end else if (GEN_LOG_ENGINE &&
                     csr_axil_req.aw.addr >= LOG_ENGINE_REG_MAP_BASE_ADDR &&
                     csr_axil_req.aw.addr <  LOG_ENGINE_REG_MAP_BASE_ADDR +
                                              LOG_ENGINE_REG_MAP_SIZE) begin
      csr_axil_aw_select = LOG_ENGINE_REG_MAP;
    end else if (csr_axil_req.aw.addr >= UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR &&
                     csr_axil_req.aw.addr <  UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR +
                                              UART_LOG_ENGINE_CTRL_REG_MAP_SIZE) begin
      csr_axil_aw_select = CTRL_REG_MAP;
    end else begin
      csr_axil_aw_select = UNDEFINED_REG_MAP;
    end
  end

  always_comb begin
    if (csr_axil_req.ar.addr >= UART_REG_MAP_BASE_ADDR &&
            csr_axil_req.ar.addr <  UART_REG_MAP_BASE_ADDR +
                                     UART_REG_MAP_SIZE) begin
      csr_axil_ar_select = UART_REG_MAP;
    end else if (GEN_LOG_ENGINE &&
                     csr_axil_req.ar.addr >= LOG_ENGINE_REG_MAP_BASE_ADDR &&
                     csr_axil_req.ar.addr <  LOG_ENGINE_REG_MAP_BASE_ADDR +
                                              LOG_ENGINE_REG_MAP_SIZE) begin
      csr_axil_ar_select = LOG_ENGINE_REG_MAP;
    end else if (csr_axil_req.ar.addr >= UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR &&
                     csr_axil_req.ar.addr <  UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR +
                                              UART_LOG_ENGINE_CTRL_REG_MAP_SIZE) begin
      csr_axil_ar_select = CTRL_REG_MAP;
    end else begin
      csr_axil_ar_select = UNDEFINED_REG_MAP;
    end
  end

  axi_lite_demux #(
    .aw_chan_t       (csr_axil_aw_chan_t),
    .w_chan_t        (csr_axil_w_chan_t),
    .b_chan_t        (csr_axil_b_chan_t),
    .ar_chan_t       (csr_axil_ar_chan_t),
    .r_chan_t        (csr_axil_r_chan_t),
    .axi_req_t       (csr_axil_req_t),
    .axi_resp_t      (csr_axil_resp_t),
    .NoMstPorts      (NUM_REG_MAPS),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1),
    .SpillR          (1'b0)
  ) u_csr_axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (1'b0),
    .slv_req_i       (csr_axil_req),
    .slv_aw_select_i (csr_axil_aw_select),
    .slv_ar_select_i (csr_axil_ar_select),
    .slv_resp_o      (csr_axil_resp),
    .mst_reqs_o      (csr_axil_reqs),
    .mst_resps_i     (csr_axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (REG_ADDR_WIDTH),
    .AXI_DATA_WIDTH (REG_DATA_WIDTH),
    .axil_req_t     (csr_axil_req_t),
    .axil_resp_t    (csr_axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (REG_DATA_WIDTH),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) u_csr_axi_lite_err_slv (
    .clk_i,
    .rst_ni,

    .axil_req_i     (csr_axil_reqs [UNDEFINED_REG_MAP]),
    .axil_resp_o    (csr_axil_resps[UNDEFINED_REG_MAP])
  );


  ////////////////
  // UART 16550 //
  ////////////////

  uart_16550 #(
    .TX_FIFO_DEPTH (UART_TX_FIFO_DEPTH),
    .RX_FIFO_DEPTH (UART_RX_FIFO_DEPTH)
  ) u_uart_16550 (
    // Global Interface
    .clk_i,
    .rst_ni,

    // AXI4-Lite Register Interface
    .axil_req_i    (uart_axil_req),
    .axil_resp_o   (uart_axil_resp),

    // UART Interface
    .rx_i          (uart_rx_i),
    .tx_o          (uart_tx_o),

    // Modem Interface
    .cts_ni        (uart_cts_ni),
    .dsr_ni        (uart_dsr_ni),
    .ri_ni         (uart_ri_ni),
    .dcd_ni        (uart_dcd_ni),

    .rts_no        (uart_rts_no),
    .dtr_no        (uart_dtr_no),
    .out1_no       (uart_out1_no),
    .out2_no       (uart_out2_no),

    // DMA Interface
    .rxrdy_o       (uart_rxrdy_o),
    .txrdy_o       (uart_txrdy_o),

    // Error Interface
    .err_o         (uart_err_o),

    // Interrupt Interface
    .irq_o         (uart_irq_o)
  );


  ////////////////
  // Log Engine //
  ////////////////

  log_engine_pkg::log_fetch_axil_req_t  log_fetch_axil_req;
  log_engine_pkg::log_fetch_axil_resp_t log_fetch_axil_resp;

  assign log_fetch_axil_req_o = log_fetch_axil_req;
  assign log_fetch_axil_resp = log_fetch_axil_resp_i;

  if (GEN_LOG_ENGINE) begin : gen_log_engine

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    uart_16550_pkg::axil_req_t  [1:0] uart_axil_reqs;
    uart_16550_pkg::axil_resp_t [1:0] uart_axil_resps;


    ////////////////
    // Log Engine //
    ////////////////

    log_engine_pkg::csr_axil_req_t  log_engine_csr_axil_req;
    log_engine_pkg::csr_axil_resp_t log_engine_csr_axil_resp;

    log_engine_pkg::log_write_axil_req_t  log_write_axil_req;
    log_engine_pkg::log_write_axil_resp_t log_write_axil_resp;

    `AXI_LITE_ASSIGN_REQ_STRUCT(log_engine_csr_axil_req, csr_axil_reqs[LOG_ENGINE_REG_MAP])
    `AXI_LITE_ASSIGN_RESP_STRUCT(csr_axil_resps[LOG_ENGINE_REG_MAP], log_engine_csr_axil_resp)

    `AXI_LITE_ASSIGN_REQ_STRUCT(uart_axil_reqs[1], log_write_axil_req)
    `AXI_LITE_ASSIGN_RESP_STRUCT(log_write_axil_resp, uart_axil_resps[1])

    log_engine #(
      .FIFO_DEPTH(LOG_ENGINE_FIFO_DEPTH)
    ) u_log_engine (
      // Global Interface
      .clk_i,
      .rst_ni,

      // AXI4-Lite Register Interface
      .csr_axil_req_i        (log_engine_csr_axil_req),
      .csr_axil_resp_o       (log_engine_csr_axil_resp),

      // AXI4-Lite Log Fetch Interface
      .log_fetch_axil_req_o  (log_fetch_axil_req),
      .log_fetch_axil_resp_i (log_fetch_axil_resp),

      // AXI4-Lite Log Write Interface
      .log_write_axil_req_o  (log_write_axil_req),
      .log_write_axil_resp_i (log_write_axil_resp),

      // DMA Interface
      .uart_tx_ready_i       (uart_txrdy_o),

      // Interrupt Interface
      .irq_o                 (log_engine_irq_o)
    );


    /////////////////////////////
    // AXI4-Lite Log Write Mux //
    /////////////////////////////

    `AXI_LITE_ASSIGN_REQ_STRUCT(uart_axil_reqs[0], csr_axil_reqs[UART_REG_MAP])
    `AXI_LITE_ASSIGN_RESP_STRUCT(csr_axil_resps[UART_REG_MAP], uart_axil_resps[0])

    axi_lite_mux #(
      // AXI4-Lite parameter and channel types
      .aw_chan_t   (uart_16550_pkg::axil_aw_chan_t),
      .w_chan_t    (uart_16550_pkg::axil_w_chan_t),
      .b_chan_t    (uart_16550_pkg::axil_b_chan_t),
      .ar_chan_t   (uart_16550_pkg::axil_ar_chan_t),
      .r_chan_t    (uart_16550_pkg::axil_r_chan_t),
      .axi_req_t   (uart_16550_pkg::axil_req_t),
      .axi_resp_t  (uart_16550_pkg::axil_resp_t),
      .NoSlvPorts  (2),
      .MaxTrans    (1),
      .FallThrough (1'b0),
      .SpillAw     (1'b1),
      .SpillW      (1'b0),
      .SpillB      (1'b0),
      .SpillAr     (1'b1),
      .SpillR      (1'b0)
    ) u_log_write_axi_lite_mux (
      .clk_i,
      .rst_ni,
      .test_i      (1'b0),
      .slv_reqs_i  (uart_axil_reqs),
      .slv_resps_o (uart_axil_resps),
      .mst_req_o   (uart_axil_req),
      .mst_resp_i  (uart_axil_resp)
    );

  end else begin : gen_no_log_engine

    `AXI_LITE_ASSIGN_REQ_STRUCT(uart_axil_req, csr_axil_reqs[UART_REG_MAP])
    `AXI_LITE_ASSIGN_RESP_STRUCT(csr_axil_resps[UART_REG_MAP], uart_axil_resp)

    assign log_fetch_axil_req = log_engine_pkg::log_fetch_axil_req_t'(0);
    assign log_engine_irq_o = 1'b0;

  end


  //////////
  // CSRs //
  //////////

  uart_log_engine_ctrl_reg_pkg::uart_log_engine_ctrl__out_t reg_out;

  uart_log_engine_ctrl_reg u_uart_log_engine_ctrl_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (csr_axil_resps[CTRL_REG_MAP].aw_ready),
    .s_axil_awvalid (csr_axil_reqs [CTRL_REG_MAP].aw_valid),
    .s_axil_awaddr  (csr_axil_reqs [CTRL_REG_MAP].aw.addr[
                             uart_log_engine_ctrl_reg_pkg::
                             UART_LOG_ENGINE_CTRL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (csr_axil_reqs [CTRL_REG_MAP].aw.prot),
    .s_axil_wready  (csr_axil_resps[CTRL_REG_MAP].w_ready),
    .s_axil_wvalid  (csr_axil_reqs [CTRL_REG_MAP].w_valid),
    .s_axil_wdata   (csr_axil_reqs [CTRL_REG_MAP].w.data),
    .s_axil_wstrb   (csr_axil_reqs [CTRL_REG_MAP].w.strb),
    .s_axil_bready  (csr_axil_reqs [CTRL_REG_MAP].b_ready),
    .s_axil_bvalid  (csr_axil_resps[CTRL_REG_MAP].b_valid),
    .s_axil_bresp   (csr_axil_resps[CTRL_REG_MAP].b.resp),
    .s_axil_arready (csr_axil_resps[CTRL_REG_MAP].ar_ready),
    .s_axil_arvalid (csr_axil_reqs [CTRL_REG_MAP].ar_valid),
    .s_axil_araddr  (csr_axil_reqs [CTRL_REG_MAP].ar.addr[
                             uart_log_engine_ctrl_reg_pkg::
                             UART_LOG_ENGINE_CTRL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (csr_axil_reqs [CTRL_REG_MAP].ar.prot),
    .s_axil_rready  (csr_axil_reqs [CTRL_REG_MAP].r_ready),
    .s_axil_rvalid  (csr_axil_resps[CTRL_REG_MAP].r_valid),
    .s_axil_rdata   (csr_axil_resps[CTRL_REG_MAP].r.data),
    .s_axil_rresp   (csr_axil_resps[CTRL_REG_MAP].r.resp),

    .hwif_out       (reg_out)
  );

  // CTRL Register
  assign uart_en_o = reg_out.CTRL.UART_EN.value;


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_KNOWN(CsrAxilRespKnownO_A, csr_axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(LogFetchAxilReqKnownO_A, log_fetch_axil_req_o)
  `OCAH_OT_ASSERT_KNOWN(UartEnKnownO_A, uart_en_o)
  `OCAH_OT_ASSERT_KNOWN(UartTxKnownO_A, uart_tx_o)
  `OCAH_OT_ASSERT_KNOWN(UartRtsNoKnownO_A, uart_rts_no)
  `OCAH_OT_ASSERT_KNOWN(UartDtrNoKnownO_A, uart_dtr_no)
  `OCAH_OT_ASSERT_KNOWN(UartOut1NoKnownO_A, uart_out1_no)
  `OCAH_OT_ASSERT_KNOWN(UartOut2NoKnownO_A, uart_out2_no)
  `OCAH_OT_ASSERT_KNOWN(UartRxrdyKnownO_A, uart_rxrdy_o)
  `OCAH_OT_ASSERT_KNOWN(UartTxrdyKnownO_A, uart_txrdy_o)
  `OCAH_OT_ASSERT_KNOWN(UartErrKnownO_A, uart_err_o)
  `OCAH_OT_ASSERT_KNOWN(UartIrqKnownO_A, uart_irq_o)
  `OCAH_OT_ASSERT_KNOWN(LogEngineIrqKnownO_A, log_engine_irq_o)

endmodule
