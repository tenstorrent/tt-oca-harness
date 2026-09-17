// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// UART 16550

// Description: UART top level wrapper file

module uart_16550
  import uart_16550_pkg::*;
#(
  // TX and RX FIFO depths
  parameter int unsigned TX_FIFO_DEPTH = 16,
  parameter int unsigned RX_FIFO_DEPTH = 16
) (
  // Global Interface
  input logic            clk_i,
  input logic            rst_ni,

  // AXI4-Lite Register Interface
  input  axil_req_t      axil_req_i,
  output axil_resp_t     axil_resp_o,

  // UART Interface
  input  logic           rx_i,
  output logic           tx_o,

  // Modem Interface
  input  logic           cts_ni,
  input  logic           dsr_ni,
  input  logic           ri_ni,
  input  logic           dcd_ni,

  output logic           rts_no,
  output logic           dtr_no,
  output logic           out1_no,
  output logic           out2_no,

  // DMA Interface
  output logic           rxrdy_o,
  output logic           txrdy_o,

  // Error Interface
  output logic           err_o,

  // Interrupt Interface
  output logic           irq_o
);

  `include "prim_assert.sv"

  // Register addresses and bitmasks
  import uart_16550_dl_addrmap_pkg::*;
  import uart_16550_main_addrmap_pkg::*;
  import uart_16550_main_wo_addrmap_pkg::*;


  /////////////////////////
  // Signal Declarations //
  /////////////////////////


  // Registers to/from hardware signals
  uart_16550_reg_in_t  reg_in;
  uart_16550_reg_out_t reg_out;


  ///////////////
  // UART Core //
  ///////////////

  uart_core #(
    .TX_FIFO_DEPTH       (TX_FIFO_DEPTH),
    .RX_FIFO_DEPTH       (RX_FIFO_DEPTH)
  ) u_uart_core (
    // Global Interface
    .clk_i,
    .rst_ni,

    // Register Interface
    .reg_out_i           (reg_out),
    .reg_in_o            (reg_in),

    // UART Interface
    .rx_i,
    .tx_o,

    // Modem Interface
    .cts_ni,
    .dsr_ni,
    .ri_ni,
    .dcd_ni,

    .rts_no,
    .dtr_no,
    .out1_no,
    .out2_no,

    // DMA Interface
    .rxrdy_o,
    .txrdy_o,

    // Error Interface
    .err_o,

    // Interrupt Interface
    .irq_o
  );


  //////////
  // CSRs //
  //////////

  axil_req_t  axil_mst_req;
  axil_resp_t axil_mst_resp;

  axil_req_t  [NUM_REG_MAPS-1:0] axil_slv_reqs;
  axil_resp_t [NUM_REG_MAPS-1:0] axil_slv_resps;

  assign axil_mst_req.aw_valid = axil_req_i.aw_valid;
  assign axil_mst_req.aw.addr  = axil_req_i.aw.addr;
  assign axil_mst_req.aw.prot  = axil_req_i.aw.prot;
  assign axil_mst_req.w_valid  = axil_req_i.w_valid;
  assign axil_mst_req.w.data   = axil_req_i.w.data;
  assign axil_mst_req.w.strb   = axil_req_i.w.strb;
  assign axil_mst_req.b_ready  = axil_req_i.b_ready;
  assign axil_mst_req.ar_valid = axil_req_i.ar_valid;
  assign axil_mst_req.ar.addr  = axil_req_i.ar.addr;
  assign axil_mst_req.ar.prot  = axil_req_i.ar.prot;
  assign axil_mst_req.r_ready  = axil_req_i.r_ready;
  assign axil_resp_o = axil_mst_resp;

  // Register map demuxing logic
  logic divisor_latch_reg_map_access;

  assign divisor_latch_reg_map_access = reg_out.main.LCR.DLAB.value;

  uart_16550_reg_map_e axil_aw_select, axil_ar_select;

  always_comb begin
    if (divisor_latch_reg_map_access &&
            axil_mst_req.aw.addr inside {uart_16550_dl_addrmap_pkg::UART_16550_DL_DLL_BASE_ADDR, uart_16550_dl_addrmap_pkg::UART_16550_DL_DLM_BASE_ADDR}) begin
      axil_aw_select = DL_REG_MAP;
    end else if (axil_mst_req.aw.addr inside {uart_16550_main_wo_addrmap_pkg::UART_16550_MAIN_WO_THR_BASE_ADDR, uart_16550_main_wo_addrmap_pkg::UART_16550_MAIN_WO_FCR_BASE_ADDR}) begin
      axil_aw_select = MAIN_WO_REG_MAP;
    end else begin
      axil_aw_select = MAIN_REG_MAP;
    end
  end

  always_comb begin
    if (divisor_latch_reg_map_access &&
            axil_mst_req.ar.addr inside {uart_16550_dl_addrmap_pkg::UART_16550_DL_DLL_BASE_ADDR, uart_16550_dl_addrmap_pkg::UART_16550_DL_DLM_BASE_ADDR}) begin
      axil_ar_select = DL_REG_MAP;
    end else begin
      axil_ar_select = MAIN_REG_MAP;
    end
  end

  axi_lite_demux #(
    .aw_chan_t       (axil_aw_chan_t),
    .w_chan_t        (axil_w_chan_t),
    .b_chan_t        (axil_b_chan_t),
    .ar_chan_t       (axil_ar_chan_t),
    .r_chan_t        (axil_r_chan_t),
    .axi_req_t       (axil_req_t),
    .axi_resp_t      (axil_resp_t),
    .NoMstPorts      (NUM_REG_MAPS),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1), // Pipeline AW to ease timing and area
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1), // Pipeline AR to ease timing and area
    .SpillR          (1'b0)
  ) u_axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (1'b0),
    .slv_req_i       (axil_mst_req),
    .slv_aw_select_i (axil_aw_select),
    .slv_ar_select_i (axil_ar_select),
    .slv_resp_o      (axil_mst_resp),
    .mst_reqs_o      (axil_slv_reqs),
    .mst_resps_i     (axil_slv_resps)
  );

  // Register blocks
  uart_16550_main_reg u_uart_16550_main_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_slv_resps[MAIN_REG_MAP].aw_ready),
    .s_axil_awvalid (axil_slv_reqs [MAIN_REG_MAP].aw_valid),
    .s_axil_awaddr  (axil_slv_reqs [MAIN_REG_MAP].aw.addr[
                             uart_16550_main_reg_pkg::UART_16550_MAIN_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (axil_slv_reqs [MAIN_REG_MAP].aw.prot),
    .s_axil_wready  (axil_slv_resps[MAIN_REG_MAP].w_ready),
    .s_axil_wvalid  (axil_slv_reqs [MAIN_REG_MAP].w_valid),
    .s_axil_wdata   (axil_slv_reqs [MAIN_REG_MAP].w.data),
    .s_axil_wstrb   (axil_slv_reqs [MAIN_REG_MAP].w.strb),
    .s_axil_bready  (axil_slv_reqs [MAIN_REG_MAP].b_ready),
    .s_axil_bvalid  (axil_slv_resps[MAIN_REG_MAP].b_valid),
    .s_axil_bresp   (axil_slv_resps[MAIN_REG_MAP].b.resp),
    .s_axil_arready (axil_slv_resps[MAIN_REG_MAP].ar_ready),
    .s_axil_arvalid (axil_slv_reqs [MAIN_REG_MAP].ar_valid),
    .s_axil_araddr  (axil_slv_reqs [MAIN_REG_MAP].ar.addr[
                             uart_16550_main_reg_pkg::UART_16550_MAIN_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (axil_slv_reqs [MAIN_REG_MAP].ar.prot),
    .s_axil_rready  (axil_slv_reqs [MAIN_REG_MAP].r_ready),
    .s_axil_rvalid  (axil_slv_resps[MAIN_REG_MAP].r_valid),
    .s_axil_rdata   (axil_slv_resps[MAIN_REG_MAP].r.data),
    .s_axil_rresp   (axil_slv_resps[MAIN_REG_MAP].r.resp),

    .hwif_in        (reg_in.main),
    .hwif_out       (reg_out.main)
  );

  uart_16550_main_wo_reg u_uart_16550_main_wo_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_slv_resps[MAIN_WO_REG_MAP].aw_ready),
    .s_axil_awvalid (axil_slv_reqs [MAIN_WO_REG_MAP].aw_valid),
    .s_axil_awaddr  (axil_slv_reqs [MAIN_WO_REG_MAP].aw.addr[
                             uart_16550_main_wo_reg_pkg::UART_16550_MAIN_WO_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (axil_slv_reqs [MAIN_WO_REG_MAP].aw.prot),
    .s_axil_wready  (axil_slv_resps[MAIN_WO_REG_MAP].w_ready),
    .s_axil_wvalid  (axil_slv_reqs [MAIN_WO_REG_MAP].w_valid),
    .s_axil_wdata   (axil_slv_reqs [MAIN_WO_REG_MAP].w.data),
    .s_axil_wstrb   (axil_slv_reqs [MAIN_WO_REG_MAP].w.strb),
    .s_axil_bready  (axil_slv_reqs [MAIN_WO_REG_MAP].b_ready),
    .s_axil_bvalid  (axil_slv_resps[MAIN_WO_REG_MAP].b_valid),
    .s_axil_bresp   (axil_slv_resps[MAIN_WO_REG_MAP].b.resp),
    .s_axil_arready (axil_slv_resps[MAIN_WO_REG_MAP].ar_ready),
    .s_axil_arvalid (axil_slv_reqs [MAIN_WO_REG_MAP].ar_valid),
    .s_axil_araddr  (axil_slv_reqs [MAIN_WO_REG_MAP].ar.addr[
                             uart_16550_main_wo_reg_pkg::UART_16550_MAIN_WO_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (axil_slv_reqs [MAIN_WO_REG_MAP].ar.prot),
    .s_axil_rready  (axil_slv_reqs [MAIN_WO_REG_MAP].r_ready),
    .s_axil_rvalid  (axil_slv_resps[MAIN_WO_REG_MAP].r_valid),
    .s_axil_rdata   (axil_slv_resps[MAIN_WO_REG_MAP].r.data),
    .s_axil_rresp   (axil_slv_resps[MAIN_WO_REG_MAP].r.resp),

    .hwif_in        (reg_in.main_wo),
    .hwif_out       (reg_out.main_wo)
  );

  uart_16550_dl_reg u_uart_16550_dl_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_slv_resps[DL_REG_MAP].aw_ready),
    .s_axil_awvalid (axil_slv_reqs [DL_REG_MAP].aw_valid),
    .s_axil_awaddr  (axil_slv_reqs [DL_REG_MAP].aw.addr[
                             uart_16550_dl_reg_pkg::UART_16550_DL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (axil_slv_reqs [DL_REG_MAP].aw.prot),
    .s_axil_wready  (axil_slv_resps[DL_REG_MAP].w_ready),
    .s_axil_wvalid  (axil_slv_reqs [DL_REG_MAP].w_valid),
    .s_axil_wdata   (axil_slv_reqs [DL_REG_MAP].w.data),
    .s_axil_wstrb   (axil_slv_reqs [DL_REG_MAP].w.strb),
    .s_axil_bready  (axil_slv_reqs [DL_REG_MAP].b_ready),
    .s_axil_bvalid  (axil_slv_resps[DL_REG_MAP].b_valid),
    .s_axil_bresp   (axil_slv_resps[DL_REG_MAP].b.resp),
    .s_axil_arready (axil_slv_resps[DL_REG_MAP].ar_ready),
    .s_axil_arvalid (axil_slv_reqs [DL_REG_MAP].ar_valid),
    .s_axil_araddr  (axil_slv_reqs [DL_REG_MAP].ar.addr[
                             uart_16550_dl_reg_pkg::UART_16550_DL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (axil_slv_reqs [DL_REG_MAP].ar.prot),
    .s_axil_rready  (axil_slv_reqs [DL_REG_MAP].r_ready),
    .s_axil_rvalid  (axil_slv_resps[DL_REG_MAP].r_valid),
    .s_axil_rdata   (axil_slv_resps[DL_REG_MAP].r.data),
    .s_axil_rresp   (axil_slv_resps[DL_REG_MAP].r.resp),

    .hwif_out       (reg_out.dl)
  );


  ////////////
  // Alerts //
  ////////////

  prim_alert_pkg::alert_tx_t unused_alert_tx;

  prim_alert_sender #(
    .AsyncOn       (1'b1),
    .IsFatal       (1'b0)
  ) u_prim_alert_sender (
    .clk_i,
    .rst_ni,
    .alert_test_i  (1'b0),
    .alert_req_i   (err_o),
    .alert_ack_o   (/* UNUSED */),
    .alert_state_o (/* UNUSED */),
    .alert_rx_i    (prim_alert_pkg::ALERT_RX_DEFAULT),
    .alert_tx_o    (unused_alert_tx)
  );


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(paramCheckTxFifoDepth,
                       TX_FIFO_DEPTH >= 4 && TX_FIFO_DEPTH <= 4096 && is_pow_of_2(TX_FIFO_DEPTH))
  `OCAH_OT_ASSERT_INIT(paramCheckRxFifoDepth,
                       RX_FIFO_DEPTH >= 4 && RX_FIFO_DEPTH <= 4096 && is_pow_of_2(RX_FIFO_DEPTH))

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(TxKnownO_A, tx_o)
  `OCAH_OT_ASSERT_KNOWN(RtsKnownO_A, rts_no)
  `OCAH_OT_ASSERT_KNOWN(DtrKnownO_A, dtr_no)
  `OCAH_OT_ASSERT_KNOWN(Out1KnownO_A, out1_no)
  `OCAH_OT_ASSERT_KNOWN(Out2KnownO_A, out2_no)
  `OCAH_OT_ASSERT_KNOWN(RxrdyKnownO_A, rxrdy_o)
  `OCAH_OT_ASSERT_KNOWN(TxrdyKnownO_A, txrdy_o)
  `OCAH_OT_ASSERT_KNOWN(ErrKnownO_A, err_o)
  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)

  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      TxFifoWptrErrTriggerAlert_A,
      u_uart_core.u_uart_txfifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_wptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      TxFifoRptrErrTriggerAlert_A,
      u_uart_core.u_uart_txfifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_rptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      RxFifoWptrErrTriggerAlert_A,
      u_uart_core.u_uart_rxfifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_wptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      RxFifoRptrErrTriggerAlert_A,
      u_uart_core.u_uart_rxfifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_rptr, unused_alert_tx)

endmodule
