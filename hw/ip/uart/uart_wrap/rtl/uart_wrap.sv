// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Map NUM_UARTS uart_log_engine_wrap instances behind one AXI-Lite port.
//
// Instance i owns the window at UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR plus
// i*UART_LOG_ENGINE_WRAP_SPACING; its UART, log-engine and CTRL bases shift by the same
// amount.
// Addresses outside every window go to an error slave that answers DECERR with read data
// 0xBADCAB1E.
// The instances' log-fetch masters share log_fetch_axil_* through an AXI-Lite mux.
// All other outputs are per-instance vectors, bit i from instance i.

module uart_wrap #(
  parameter int unsigned        NUM_UARTS             = 4,  // UART instance count; 1 to
                                                            // MaxNumUarts.
  parameter int unsigned        UART_TX_FIFO_DEPTH    = 32,  // Per-UART TX FIFO depth.
  parameter int unsigned        UART_RX_FIFO_DEPTH    = 32,  // Per-UART RX FIFO depth.
  parameter bit [NUM_UARTS-1:0] GEN_LOG_ENGINES       = {NUM_UARTS{1'b1}},  // Bit i instantiates the log engine of UART i.
  parameter int unsigned        LOG_ENGINE_FIFO_DEPTH = 4,  // Entries in each log engine's
                                                            // read-data FIFO.

  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_LOG_ENGINE_WRAP_0__REG_MAP_BASE_ADDR = 0,  // Base of instance 0's decode window.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_LOG_ENGINE_WRAP_0__REG_MAP_SIZE      = 0,  // Size of each instance's decode window.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_LOG_ENGINE_WRAP_SPACING              = 0,  // Address stride between instance windows and their internal map bases.

  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_REG_MAP_BASE_ADDR = 0,  // Instance 0's UART register-map base.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_REG_MAP_SIZE      = 0,  // Per-instance UART register-map size.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] LOG_ENGINE_REG_MAP_BASE_ADDR = 0,  // Instance 0's log-engine register-map base.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] LOG_ENGINE_REG_MAP_SIZE      = 0,  // Per-instance log-engine register-map size.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_LOG_ENGINE_CTRL_REG_MAP_BASE_ADDR = 0,  // Instance 0's CTRL register-map base.
  parameter bit [uart_wrap_pkg::RegAddrWidth-1:0] UART_LOG_ENGINE_CTRL_REG_MAP_SIZE = 0,  // Per-instance CTRL register-map size.

  localparam int unsigned NumRegMaps = NUM_UARTS + 1,  // +1 for error slave.
  localparam type uart_wrap_reg_map_select_t = logic [$clog2(NumRegMaps)-1:0],  // UART-wrap window select type.
  localparam uart_wrap_reg_map_select_t UndefinedRegMap =  // Unmapped address sink select.
        uart_wrap_reg_map_select_t'(NumRegMaps - 1)
) (
  input  logic                                 clk_i,  // System clock.
  input  logic                                 rst_ni,  // Active-low reset.

  input  uart_wrap_pkg::csr_axil_req_t                        csr_axil_req_i,  // Register-port request, decoded onto the instance windows.
  output uart_wrap_pkg::csr_axil_resp_t                       csr_axil_resp_o,  // Csr AXI-Lite resp.

  output log_engine_pkg::log_fetch_axil_req_t  log_fetch_axil_req_o,  // Log-fetch request muxed from every instance's log engine.
  input  log_engine_pkg::log_fetch_axil_resp_t log_fetch_axil_resp_i,  // Log fetch AXI-Lite resp.

  output logic [NUM_UARTS-1:0]                 uart_en_o,  // Per-UART CTRL.UART_EN value,
                                                           // active-high; not used inside the
                                                           // wrapper.

  input  logic [NUM_UARTS-1:0]                 uart_rx_i,  // Per-UART serial receive data;
                                                           // asynchronous, synchronized in
                                                           // uart_core.
  output logic [NUM_UARTS-1:0]                 uart_tx_o,  // Serial transmit data to the pad, one
                                                           // bit per UART; idles high.

  input  logic [NUM_UARTS-1:0]                 uart_cts_ni,  // uart cts, active-low (UART Modem
                                                             // Interface).
  input  logic [NUM_UARTS-1:0]                 uart_dsr_ni,  // uart dsr, active-low.
  input  logic [NUM_UARTS-1:0]                 uart_ri_ni,  // uart ri, active-low.
  input  logic [NUM_UARTS-1:0]                 uart_dcd_ni,  // uart dcd, active-low.

  output logic [NUM_UARTS-1:0]                 uart_rts_no,  // uart rts, active-low.
  output logic [NUM_UARTS-1:0]                 uart_dtr_no,  // uart dtr, active-low.
  output logic [NUM_UARTS-1:0]                 uart_out1_no,  // uart out1, active-low.
  output logic [NUM_UARTS-1:0]                 uart_out2_no,  // uart out2, active-low.

  output logic [NUM_UARTS-1:0]                 uart_rxrdy_o,  // Per-UART DMA receive request,
                                                              // active-high: in mode 0 while the RX
                                                              // FIFO is not empty; in mode 1 from
                                                              // the trigger level or a character
                                                              // timeout until the FIFO empties.
  output logic [NUM_UARTS-1:0]                 uart_txrdy_o,  // Per-UART DMA transmit request,
                                                              // active-high: in mode 0 while the TX
                                                              // FIFO is empty; in mode 1 until it
                                                              // fills, then again once it drains.

  output logic [NUM_UARTS-1:0]                 uart_err_o,  // Per-UART FIFO or holding-register
                                                            // integrity error, active-high.

  output logic [NUM_UARTS-1:0]                 uart_irq_o,  // Per-UART interrupt request,
                                                            // active-high.
  output logic [NUM_UARTS-1:0]                 log_engine_irq_o  // Per-UART log-engine interrupt,
                                                                 // active-high; low for a UART
                                                                 // generated without a log engine.
);

  `include "axi/assign.svh"
  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  uart_wrap_pkg::csr_axil_req_t  [NumRegMaps-1:0] csr_axil_reqs;
  uart_wrap_pkg::csr_axil_resp_t [NumRegMaps-1:0] csr_axil_resps;


  //////////////////////////////
  // AXI4-Lite Register Demux //
  //////////////////////////////

  uart_wrap_reg_map_select_t csr_axil_aw_select, csr_axil_ar_select;

  always_comb begin
    csr_axil_aw_select = UndefinedRegMap;
    csr_axil_ar_select = UndefinedRegMap;

    for (int i = 0; i < NUM_UARTS; i++) begin
      logic [uart_wrap_pkg::RegAddrWidth-1:0] uart_i_base_addr;
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
    .NoMstPorts      (NumRegMaps),
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
    .slv_req_i       (csr_axil_req_i),
    .slv_aw_select_i (csr_axil_aw_select),
    .slv_ar_select_i (csr_axil_ar_select),
    .slv_resp_o      (csr_axil_resp_o),
    .mst_reqs_o      (csr_axil_reqs),
    .mst_resps_i     (csr_axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (uart_wrap_pkg::RegAddrWidth),
    .AXI_DATA_WIDTH (uart_wrap_pkg::RegDataWidth),
    .axil_req_t     (uart_wrap_pkg::csr_axil_req_t),
    .axil_resp_t    (uart_wrap_pkg::csr_axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (uart_wrap_pkg::RegDataWidth),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) u_csr_axi_lite_err_slv (
    .clk_i,
    .rst_ni,

    .axil_req_i     (csr_axil_reqs [UndefinedRegMap]),
    .axil_resp_o    (csr_axil_resps[UndefinedRegMap])
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
  ) u_log_fetch_axi_lite_mux (
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
    ) u_uart_log_engine_wrap (
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
                       NUM_UARTS > 0 && NUM_UARTS <= uart_wrap_pkg::MaxNumUarts)

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
