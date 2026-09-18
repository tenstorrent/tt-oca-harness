// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// UART Wrapper
//
//-----------------------------------------------------------------------------

module uart_wrap #(
  parameter int unsigned        NUM_UARTS             = 4,
  parameter int unsigned        UART_TX_FIFO_DEPTH    = 32,
  parameter int unsigned        UART_RX_FIFO_DEPTH    = 32,
  parameter bit [NUM_UARTS-1:0] GEN_LOG_ENGINES       = {NUM_UARTS{1'b1}},
  parameter int unsigned        LOG_ENGINE_FIFO_DEPTH = 4,

  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE      = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_WRAP_SPACING              = 0,

  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_REG_MAP_BASE_ADDR = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_REG_MAP_SIZE      = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] LOG_ENGINE_REG_MAP_BASE_ADDR = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] LOG_ENGINE_REG_MAP_SIZE      = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR = 0,
  parameter bit [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] UART_LOG_ENGINE_CTRL_REG_MAP_SIZE = 0,

  localparam int unsigned NUM_REG_MAPS = NUM_UARTS + 1, // +1 for error slave
  localparam type uart_wrap_reg_map_select_t = logic [$clog2(NUM_REG_MAPS)-1:0],
  localparam uart_wrap_reg_map_select_t UNDEFINED_REG_MAP =
        uart_wrap_reg_map_select_t'(NUM_REG_MAPS - 1)
) (
  // Global Interface
  input  logic                                 clk_i,
  input  logic                                 rst_ni,

  // AXI4-Lite Register Interface
  input  uart_wrap_pkg::csr_axil_req_t                        csr_axil_req_i,
  output uart_wrap_pkg::csr_axil_resp_t                       csr_axil_resp_o,

  // AXI4-Lite Log fetch Interface
  output log_engine_pkg::log_fetch_axil_req_t  log_fetch_axil_req_o,
  input  log_engine_pkg::log_fetch_axil_resp_t log_fetch_axil_resp_i,

  // Control Interface
  output logic [NUM_UARTS-1:0]                 uart_en_o,

  // UART Interface
  input  logic [NUM_UARTS-1:0]                 uart_rx_i,
  output logic [NUM_UARTS-1:0]                 uart_tx_o,

  // UART Modem Interface
  input  logic [NUM_UARTS-1:0]                 uart_cts_ni,
  input  logic [NUM_UARTS-1:0]                 uart_dsr_ni,
  input  logic [NUM_UARTS-1:0]                 uart_ri_ni,
  input  logic [NUM_UARTS-1:0]                 uart_dcd_ni,

  output logic [NUM_UARTS-1:0]                 uart_rts_no,
  output logic [NUM_UARTS-1:0]                 uart_dtr_no,
  output logic [NUM_UARTS-1:0]                 uart_out1_no,
  output logic [NUM_UARTS-1:0]                 uart_out2_no,

  // UART DMA Interface
  output logic [NUM_UARTS-1:0]                 uart_rxrdy_o,
  output logic [NUM_UARTS-1:0]                 uart_txrdy_o,

  // UART Error Interface
  output logic [NUM_UARTS-1:0]                 uart_err_o,

  // Interrupt Interface
  output logic [NUM_UARTS-1:0]                 uart_irq_o,
  output logic [NUM_UARTS-1:0]                 log_engine_irq_o
);

  `include "axi/assign.svh"
  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  uart_wrap_pkg::csr_axil_req_t  [NUM_REG_MAPS-1:0] csr_axil_reqs;
  uart_wrap_pkg::csr_axil_resp_t [NUM_REG_MAPS-1:0] csr_axil_resps;


  //////////////////////////////
  // AXI4-Lite Register Demux //
  //////////////////////////////

  uart_wrap_reg_map_select_t csr_axil_aw_select, csr_axil_ar_select;

  always_comb begin
    csr_axil_aw_select = UNDEFINED_REG_MAP;
    csr_axil_ar_select = UNDEFINED_REG_MAP;

    for (int i = 0; i < NUM_UARTS; i++) begin
      logic [uart_wrap_pkg::REG_ADDR_WIDTH-1:0] uart_i_base_addr;
      uart_i_base_addr = UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR + i * UART_LOG_ENGINE_WRAP_SPACING;
      if (csr_axil_req_i.aw.addr >= uart_i_base_addr &&
                csr_axil_req_i.aw.addr <  uart_i_base_addr +
                                          UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE) begin
        csr_axil_aw_select = uart_wrap_reg_map_select_t'(i);
      end
      if (csr_axil_req_i.ar.addr >= uart_i_base_addr &&
                csr_axil_req_i.ar.addr <  uart_i_base_addr +
                                          UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE) begin
        csr_axil_ar_select = uart_wrap_reg_map_select_t'(i);
      end
    end
  end

  axi_lite_demux #(
    .aw_chan_t       (uart_wrap_pkg::csr_axil_aw_chan_t),
    .w_chan_t        (uart_wrap_pkg::csr_axil_w_chan_t),
    .b_chan_t        (uart_wrap_pkg::csr_axil_b_chan_t),
    .ar_chan_t       (uart_wrap_pkg::csr_axil_ar_chan_t),
    .r_chan_t        (uart_wrap_pkg::csr_axil_r_chan_t),
    .axi_req_t       (uart_wrap_pkg::csr_axil_req_t),
    .axi_resp_t      (uart_wrap_pkg::csr_axil_resp_t),
    .NoMstPorts      (NUM_REG_MAPS),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1),
    .SpillR          (1'b0)
  ) csr_axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (1'b0),
    .slv_req_i       (csr_axil_req_i),
    .slv_aw_select_i (csr_axil_aw_select),
    .slv_ar_select_i (csr_axil_ar_select),
    .slv_resp_o      (csr_axil_resp_o),
    .mst_reqs_o      (csr_axil_reqs),
    .mst_resps_i     (csr_axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (uart_wrap_pkg::REG_ADDR_WIDTH),
    .AXI_DATA_WIDTH (uart_wrap_pkg::REG_DATA_WIDTH),
    .axil_req_t     (uart_wrap_pkg::csr_axil_req_t),
    .axil_resp_t    (uart_wrap_pkg::csr_axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (uart_wrap_pkg::REG_DATA_WIDTH),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) csr_axi_lite_err_slv (
    .clk_i,
    .rst_ni,

    .axil_req_i     (csr_axil_reqs [UNDEFINED_REG_MAP]),
    .axil_resp_o    (csr_axil_resps[UNDEFINED_REG_MAP])
  );


  ////////////////////////////////
  // UART & Log Engine Wrappers //
  ////////////////////////////////

  log_engine_pkg::log_fetch_axil_req_t  [NUM_UARTS-1:0] log_fetch_axil_reqs;
  log_engine_pkg::log_fetch_axil_resp_t [NUM_UARTS-1:0] log_fetch_axil_resps;

  axi_lite_mux #(
    .aw_chan_t   (log_engine_pkg::log_fetch_axil_aw_chan_t),
    .w_chan_t    (log_engine_pkg::log_fetch_axil_w_chan_t),
    .b_chan_t    (log_engine_pkg::log_fetch_axil_b_chan_t),
    .ar_chan_t   (log_engine_pkg::log_fetch_axil_ar_chan_t),
    .r_chan_t    (log_engine_pkg::log_fetch_axil_r_chan_t),
    .axi_req_t   (log_engine_pkg::log_fetch_axil_req_t),
    .axi_resp_t  (log_engine_pkg::log_fetch_axil_resp_t),
    .NoSlvPorts  (NUM_UARTS),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) log_fetch_axi_lite_mux (
    .clk_i,
    .rst_ni,
    .test_i      (1'b0),
    .slv_reqs_i  (log_fetch_axil_reqs),
    .slv_resps_o (log_fetch_axil_resps),
    .mst_req_o   (log_fetch_axil_req_o),
    .mst_resp_i  (log_fetch_axil_resp_i)
  );

  for (genvar i = 0; i < NUM_UARTS; i++) begin : gen_uart_log_engine_wraps

    uart_log_engine_wrap_pkg::csr_axil_req_t  uart_log_engine_wrap_csr_axil_req;
    uart_log_engine_wrap_pkg::csr_axil_resp_t uart_log_engine_wrap_csr_axil_resp;

    `AXI_LITE_ASSIGN_REQ_STRUCT(uart_log_engine_wrap_csr_axil_req, csr_axil_reqs[i])
    `AXI_LITE_ASSIGN_RESP_STRUCT(csr_axil_resps[i], uart_log_engine_wrap_csr_axil_resp)

    uart_log_engine_wrap #(
      .UART_TX_FIFO_DEPTH    (UART_TX_FIFO_DEPTH),
      .UART_RX_FIFO_DEPTH    (UART_RX_FIFO_DEPTH),
      .GEN_LOG_ENGINE        (GEN_LOG_ENGINES[i]),
      .LOG_ENGINE_FIFO_DEPTH (LOG_ENGINE_FIFO_DEPTH),

      .UART_REG_MAP_BASE_ADDR (UART_REG_MAP_BASE_ADDR + i * UART_LOG_ENGINE_WRAP_SPACING),
      .UART_REG_MAP_SIZE      (UART_REG_MAP_SIZE),
      .LOG_ENGINE_REG_MAP_BASE_ADDR (LOG_ENGINE_REG_MAP_BASE_ADDR + i * UART_LOG_ENGINE_WRAP_SPACING),
      .LOG_ENGINE_REG_MAP_SIZE      (LOG_ENGINE_REG_MAP_SIZE),
      .UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR (UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR + i * UART_LOG_ENGINE_WRAP_SPACING),
      .UART_LOG_ENGINE_CTRL_REG_MAP_SIZE (UART_LOG_ENGINE_CTRL_REG_MAP_SIZE)
    ) uart_log_engine_wrap (
      // Global Interface
      .clk_i,
      .rst_ni,

      // AXI4-Lite Register Interface
      .csr_axil_req_i        (uart_log_engine_wrap_csr_axil_req),
      .csr_axil_resp_o       (uart_log_engine_wrap_csr_axil_resp),

      // AXI4-Lite Log Fetch Interface
      .log_fetch_axil_req_o  (log_fetch_axil_reqs [i]),
      .log_fetch_axil_resp_i (log_fetch_axil_resps[i]),

      // Control Interface
      .uart_en_o             (uart_en_o[i]),

      // UART Interface
      .uart_rx_i             (uart_rx_i[i]),
      .uart_tx_o             (uart_tx_o[i]),

      // UART Modem Interface
      .uart_cts_ni           (uart_cts_ni[i]),
      .uart_dsr_ni           (uart_dsr_ni[i]),
      .uart_ri_ni            (uart_ri_ni [i]),
      .uart_dcd_ni           (uart_dcd_ni[i]),

      .uart_rts_no           (uart_rts_no [i]),
      .uart_dtr_no           (uart_dtr_no [i]),
      .uart_out1_no          (uart_out1_no[i]),
      .uart_out2_no          (uart_out2_no[i]),

      // UART DMA Interface
      .uart_rxrdy_o          (uart_rxrdy_o[i]),
      .uart_txrdy_o          (uart_txrdy_o[i]),

      // UART Error Interface
      .uart_err_o            (uart_err_o[i]),

      // Interrupt Interface
      .uart_irq_o            (uart_irq_o      [i]),
      .log_engine_irq_o      (log_engine_irq_o[i])
    );

  end


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(paramCheckNumUarts_A,
                       NUM_UARTS > 0 && NUM_UARTS <= uart_wrap_pkg::MAX_NUM_UARTS)

  `OCAH_OT_ASSERT_KNOWN(CsrAxilRespKnownO_A, csr_axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(LogFetchAxilReqKnownO_A, log_fetch_axil_req_o)
  `OCAH_OT_ASSERT_KNOWN(UartEnKnownO_A, uart_en_o)
  `OCAH_OT_ASSERT_KNOWN(UartTxKnownO_A, uart_tx_o)
  `OCAH_OT_ASSERT_KNOWN(UartRtsKnownO_A, uart_rts_no)
  `OCAH_OT_ASSERT_KNOWN(UartDtrKnownO_A, uart_dtr_no)
  `OCAH_OT_ASSERT_KNOWN(UartOut1KnownO_A, uart_out1_no)
  `OCAH_OT_ASSERT_KNOWN(UartOut2KnownO_A, uart_out2_no)
  `OCAH_OT_ASSERT_KNOWN(UartRdyKnownO_A, uart_rxrdy_o)
  `OCAH_OT_ASSERT_KNOWN(UartTdyKnownO_A, uart_txrdy_o)
  `OCAH_OT_ASSERT_KNOWN(UartErrKnownO_A, uart_err_o)
  `OCAH_OT_ASSERT_KNOWN(UartIrqKnownO_A, uart_irq_o)
  `OCAH_OT_ASSERT_KNOWN(LogEngineIrqKnownO_A, log_engine_irq_o)

endmodule
