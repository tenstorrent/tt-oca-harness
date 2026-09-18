//-----------------------------------------------------------------------------
// SPI Controller
//
// Copyright 2025 Tenstorrent Inc.
//-----------------------------------------------------------------------------

// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0
//
// Serial Peripheral Interface (SPI) Host module.
//
//


module spi_controller
  import spi_controller_pkg::*;
#(
  parameter int unsigned NUM_CS         = 1,
  parameter byte_order_e BYTE_ORDER     = LITTLE_ENDIAN,
  parameter int unsigned TX_FIFO_DEPTH  = 72,
  parameter int unsigned RX_FIFO_DEPTH  = 64,
  parameter int unsigned CMD_FIFO_DEPTH = 4,

  localparam int CSW = prim_util_pkg::vbits(NUM_CS)
) (
  // Global Interface
  input  logic              clk_i,
  input  logic              rst_ni,

  // AXI4-Lite Register Interface
  input  axil_req_t         axil_req_i,
  output axil_resp_t        axil_resp_o,

  // SPI Interface
  output logic              sck_o,
  output logic              sck_en_o,
  output logic [NUM_CS-1:0] cs_no,
  output logic [NUM_CS-1:0] cs_en_o,
  output logic [3:0]        io_o,
  output logic [3:0]        io_en_o,
  input        [3:0]        io_i,

  // DMA Interface
  output logic              lsio_trigger_o,

  // Interrupt Interface
  output logic              irq_o,

  // Status Interface
  output logic              busy_o
);

  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic error_intr, spi_event_intr;

  spi_controller_reg_pkg::spi_controller__in_t  reg_in;
  spi_controller_reg_pkg::spi_controller__out_t reg_out;

  logic              sck;
  logic [NUM_CS-1:0] csb;
  logic [3:0]        sd_out;
  logic [3:0] sd_en, sd_en_core;
  logic [3:0]        sd_i;
  logic              output_en;

  assign output_en = reg_out.CTRL.OUTPUT_EN.value;
  assign sd_en     = output_en ? sd_en_core : 4'h0;

  assign sck_o    = sck;
  assign sck_en_o = output_en;
  assign cs_no    = csb;
  assign cs_en_o  = output_en;
  assign io_o     = sd_out;
  assign io_en_o  = sd_en;

  assign sd_i = io_i;

  assign reg_in.STATUS.BYTEORDER.next = BYTE_ORDER;

  logic command_valid;
  logic core_command_valid;
  logic command_busy;
  logic core_command_ready;

  command_t core_command, command;
  logic [CSW-1:0] core_command_csid, command_csid;
  logic error_csid_inval;
  logic error_cmd_inval;
  logic error_busy;
  logic test_csid_inval;
  logic test_dir_inval;
  logic test_speed_inval;

  assign test_csid_inval = reg_out.CSID.CSID.value >= NUM_CS;

  always_comb begin
    test_speed_inval           = 1'b1;
    test_dir_inval             = 1'b1;
    unique case (reg_out.CMD.wr_data.SPEED)
      Standard: begin
        test_dir_inval   = 1'b0;
        test_speed_inval = 1'b0;
      end
      Dual, Quad: begin
        test_dir_inval   = reg_out.CMD.wr_data.DIRECTION == Bidir;
        test_speed_inval = 1'b0;
      end
      default: begin
      end
    endcase
  end

  always_comb begin
    command.segment.cmd_rd_en = 1'b0;
    command.segment.cmd_wr_en = 1'b0;
    unique case (reg_out.CMD.wr_data.DIRECTION)
      RdOnly: begin
        command.segment.cmd_rd_en = 1'b1;
      end
      WrOnly: begin
        command.segment.cmd_wr_en = 1'b1;
      end
      Bidir: begin
        command.segment.cmd_rd_en = 1'b1;
        command.segment.cmd_wr_en = 1'b1;
      end
      default: begin
      end
    endcase
  end

  assign error_csid_inval = command_valid & ~command_busy &
                                test_csid_inval;
  assign error_cmd_inval  = command_valid & ~command_busy &
                                (test_speed_inval | test_dir_inval);

  assign command_csid = test_csid_inval ? '0 : reg_out.CSID.CSID.value[CSW-1:0];

  assign command.configopts.clkdiv   = reg_out.CFG.CLKDIV.value;
  assign command.configopts.csnidle  = reg_out.CFG.CSNIDLE.value;
  assign command.configopts.csnlead  = reg_out.CFG.CSNLEAD.value;
  assign command.configopts.csntrail = reg_out.CFG.CSNTRAIL.value;
  assign command.configopts.full_cyc = reg_out.CFG.FULLCYC.value;
  assign command.configopts.cpha     = reg_out.CFG.CPHA.value;
  assign command.configopts.cpol     = reg_out.CFG.CPOL.value;

  // W164b fix: make the zero-extension explicit at the assignment site to be clear.
  assign command.segment.len   = 20'(reg_out.CMD.wr_data.LEN);
  assign command.segment.csaat = reg_out.CMD.wr_data.CSAAT;
  assign command.segment.speed = reg_out.CMD.wr_data.SPEED;

  assign reg_in.CMD.wr_ack = reg_out.CMD.req && reg_out.CMD.req_is_wr;
  assign command_valid     = reg_out.CMD.req && reg_out.CMD.req_is_wr && |reg_out.CMD.wr_biten;

  logic active;
  logic rx_stall;
  logic tx_stall;

  assign reg_in.STATUS.READY.next   = ~command_busy;
  assign reg_in.STATUS.ACTIVE.next  = active;
  assign reg_in.STATUS.RXSTALL.next = rx_stall;
  assign reg_in.STATUS.TXSTALL.next = tx_stall;

  logic sw_rst;

  logic [3:0]  cmd_qd;

  spi_controller_command_queue #(
    .CmdDepth             (CMD_FIFO_DEPTH),
    .NumCS                (NUM_CS)
  ) command_queue (
    .clk_i,
    .rst_ni,
    .command_i            (command),
    .command_csid_i       (command_csid),
    .command_valid_i      (command_valid),
    .command_busy_o       (command_busy),
    .core_command_o       (core_command),
    .core_command_csid_o  (core_command_csid),
    .core_command_valid_o (core_command_valid),
    .core_command_ready_i (core_command_ready),
    .error_busy_o         (error_busy),
    .qd_o                 (cmd_qd),
    .sw_rst_i             (sw_rst)
  );

  logic [31:0] tx_data;
  logic [3:0]  tx_be;
  logic        tx_valid;
  logic        tx_ready;

  logic [31:0] rx_data;
  logic        rx_valid;
  logic        rx_ready;

  assign tx_data  = reg_out.TXDATA.wr_data.TXDATA & reg_out.TXDATA.wr_biten;
  assign tx_be    = {|reg_out.TXDATA.wr_biten[3*8 +: 8],
                       |reg_out.TXDATA.wr_biten[2*8 +: 8],
                       |reg_out.TXDATA.wr_biten[1*8 +: 8],
                       |reg_out.TXDATA.wr_biten[0*8 +: 8]};
  assign tx_valid = reg_out.TXDATA.req && reg_out.TXDATA.req_is_wr && |reg_out.TXDATA.wr_biten;
  assign reg_in.TXDATA.wr_ack = reg_out.TXDATA.req && reg_out.TXDATA.req_is_wr;

  assign reg_in.RXDATA.rd_data.RXDATA = rx_data;
  assign rx_ready                     = reg_out.RXDATA.req && !reg_out.RXDATA.req_is_wr;
  assign reg_in.RXDATA.rd_ack = reg_out.RXDATA.req && !reg_out.RXDATA.req_is_wr;

  logic [31:0] core_tx_data;
  logic [3:0]  core_tx_be;
  logic        core_tx_valid;
  logic        core_tx_ready;
  logic        core_tx_byte_select_full;

  logic [31:0] core_rx_data;
  logic        core_rx_valid;
  logic        core_rx_ready;

  logic [7:0]  rx_watermark;
  logic [7:0]  tx_watermark;
  logic [7:0]  rx_qd;
  logic [7:0]  tx_qd;

  logic tx_empty, tx_full, tx_wm;
  logic rx_empty, rx_full, rx_wm;

  assign rx_watermark = reg_out.CTRL.RX_WATERMARK.value;
  assign tx_watermark = reg_out.CTRL.TX_WATERMARK.value;

  assign reg_in.STATUS.TXQD.next    = tx_qd;
  assign reg_in.STATUS.RXQD.next    = rx_qd;
  assign reg_in.STATUS.CMDQD.next   = cmd_qd;
  assign reg_in.STATUS.TXWM.next    = tx_wm;
  assign reg_in.STATUS.RXWM.next    = rx_wm;
  assign reg_in.STATUS.RXEMPTY.next = rx_empty;
  assign reg_in.STATUS.TXEMPTY.next = tx_empty;
  assign reg_in.STATUS.RXFULL.next  = rx_full;
  assign reg_in.STATUS.TXFULL.next  = tx_full;

  logic error_overflow, error_underflow;
  logic error_access_inval;

  // Since the DATA FIFOs are essentially directly connected to SW registers, it is an error if
  // there is ever a need for flow control.
  assign error_overflow    = tx_valid & ~tx_ready;
  assign error_underflow   = rx_ready & ~rx_valid;
  logic access_valid;
  assign error_access_inval = tx_valid & ~access_valid;

  always_comb begin
    unique case (tx_be)
      4'b1000, 4'b0100, 4'b0010, 4'b0001, 4'b1100, 4'b0110, 4'b0011, 4'b1111: begin
        access_valid = 1'b1;
      end
      default: begin
        access_valid = 1'b0;
      end
    endcase
  end

  logic tx_valid_checked;
  assign tx_valid_checked = tx_valid & ~error_overflow & ~error_access_inval;

  // Note on ByteOrder and ByteSwapping.
  // ByteOrder == 1 is for Little-Endian transmission (i.e. LSB first), which is achieved by
  // default with the prim_packer_fifo implementation.  Thus we have to swap if Big-Endian
  // transmission is required (i.e. if ByteOrder == 0).
  spi_controller_data_fifos #(
    .TxDepth                    (TX_FIFO_DEPTH),
    .RxDepth                    (RX_FIFO_DEPTH),
    .SwapBytes                  (BYTE_ORDER == BIG_ENDIAN)
  ) data_fifos (
    .clk_i,
    .rst_ni,

    .tx_data_i                  (tx_data),
    .tx_be_i                    (tx_be),
    .tx_valid_i                 (tx_valid_checked),
    .tx_ready_o                 (tx_ready),
    .tx_watermark_i             (tx_watermark),

    .core_tx_data_o             (core_tx_data),
    .core_tx_be_o               (core_tx_be),
    .core_tx_valid_o            (core_tx_valid),
    .core_tx_ready_i            (core_tx_ready),
    .core_tx_byte_select_full_i (core_tx_byte_select_full),

    .core_rx_data_i             (core_rx_data),
    .core_rx_valid_i            (core_rx_valid),
    .core_rx_ready_o            (core_rx_ready),

    .rx_data_o                  (rx_data),
    .rx_valid_o                 (rx_valid),
    .rx_ready_i                 (rx_ready),
    .rx_watermark_i             (rx_watermark),

    .tx_empty_o                 (tx_empty),
    .tx_full_o                  (tx_full),
    .tx_qd_o                    (tx_qd),
    .tx_wm_o                    (tx_wm),
    .rx_empty_o                 (rx_empty),
    .rx_full_o                  (rx_full),
    .rx_qd_o                    (rx_qd),
    .rx_wm_o                    (rx_wm),

    .sw_rst_i                   (sw_rst)
  );

  logic en_sw;
  logic enb_error;
  logic en;

  assign en     = en_sw & ~enb_error;
  assign sw_rst = reg_out.CTRL.SW_RST.value;
  assign en_sw  = reg_out.CTRL.SPIEN.value;

  spi_controller_core #(
    .NumCS(NUM_CS)
  ) spi_controller_core (
    .clk_i,
    .rst_ni,

    .command_i             (core_command),
    .command_csid_i        (core_command_csid),
    .command_valid_i       (core_command_valid),
    .command_ready_o       (core_command_ready),
    .en_i                  (en),
    .tx_data_i             (core_tx_data),
    .tx_be_i               (core_tx_be),
    .tx_valid_i            (core_tx_valid),
    .tx_ready_o            (core_tx_ready),
    .tx_byte_select_full_o (core_tx_byte_select_full),
    .rx_data_o             (core_rx_data),
    .rx_valid_o            (core_rx_valid),
    .rx_ready_i            (core_rx_ready),
    .sck_o                 (sck),
    .csb_o                 (csb),
    .sd_o                  (sd_out),
    .sd_en_o               (sd_en_core),
    .sd_i,
    .rx_stall_o            (rx_stall),
    .tx_stall_o            (tx_stall),
    .sw_rst_i              (sw_rst),
    .active_o              (active)
  );

  assign reg_in.ERROR_STATUS.ACCESSINVAL.next = error_access_inval;
  assign reg_in.ERROR_STATUS.CSIDINVAL.next   = error_csid_inval;
  assign reg_in.ERROR_STATUS.CMDINVAL.next    = error_cmd_inval;
  assign reg_in.ERROR_STATUS.UNDERFLOW.next   = error_underflow;
  assign reg_in.ERROR_STATUS.OVERFLOW.next    = error_overflow;
  assign reg_in.ERROR_STATUS.CMDBUSY.next     = error_busy;

  logic [5:0] error_vector;
  logic [5:0] error_mask;
  logic       status_error;

  assign error_vector = {
        reg_out.ERROR_STATUS.ACCESSINVAL.value,
        reg_out.ERROR_STATUS.CSIDINVAL.value,
        reg_out.ERROR_STATUS.CMDINVAL.value,
        reg_out.ERROR_STATUS.UNDERFLOW.value,
        reg_out.ERROR_STATUS.OVERFLOW.value,
        reg_out.ERROR_STATUS.CMDBUSY.value
    };

  // Which classes of latched error escalate to an error interrupt. ACCESSINVAL
  // is a bus error with no CSR.ERROR_ENABLE bit, so it always escalates.
  assign error_mask = {
        1'b1,
        reg_out.ERROR_ENABLE.CSIDINVAL.value,
        reg_out.ERROR_ENABLE.CMDINVAL.value,
        reg_out.ERROR_ENABLE.UNDERFLOW.value,
        reg_out.ERROR_ENABLE.OVERFLOW.value,
        reg_out.ERROR_ENABLE.CMDBUSY.value
    };

  assign status_error = |(error_vector & error_mask);

  // Deliberately the unmasked aggregate: ERROR_ENABLE gates the interrupt only.
  // Any latched error still holds the core off until software clears
  // ERROR_STATUS, matching the upstream spi_host.
  assign enb_error = reg_out.ERROR_STATUS.intr;

  assign error_intr = (status_error || reg_out.INTR_TEST.ERROR.value) &&
                        reg_out.INTR_ENABLE.ERROR.value;
  assign reg_in.INTR_STATUS.ERROR.next = error_intr;

  logic status_spi_event;
  logic status_idle, status_ready, status_tx_wm, status_rx_wm, status_tx_empty, status_rx_full;
  logic [5:0] event_vector;
  logic [5:0] event_mask;

  assign status_idle     = ~active;
  assign status_ready    = ~command_busy;
  assign status_tx_wm    = tx_wm;
  assign status_rx_wm    = rx_wm;
  assign status_tx_empty = tx_empty;
  assign status_rx_full  = rx_full;

  assign event_vector = {
        status_idle,
        status_ready,
        status_tx_wm,
        status_rx_wm,
        status_tx_empty,
        status_rx_full
    };

  assign event_mask = {
        reg_out.EVENT_ENABLE.IDLE.value,
        reg_out.EVENT_ENABLE.READY.value,
        reg_out.EVENT_ENABLE.TXWM.value,
        reg_out.EVENT_ENABLE.RXWM.value,
        reg_out.EVENT_ENABLE.TXEMPTY.value,
        reg_out.EVENT_ENABLE.RXFULL.value
    };

  // Qualify interrupt sources individually with dedicated mask register CSR.EVENT_ENABLE
  assign status_spi_event = |(event_vector & event_mask);

  // Flop trigger signal to avoid glitches on the output
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      lsio_trigger_o <= 1'b0;
    end else begin
      lsio_trigger_o <= tx_wm | rx_wm;
    end
  end

  assign spi_event_intr = (status_spi_event || reg_out.INTR_TEST.SPI_EVENT.value) &&
                            reg_out.INTR_ENABLE.SPI_EVENT.value;
  assign reg_in.INTR_STATUS.SPI_EVENT.next = spi_event_intr;


  /////////////////////
  // Interrupt Logic //
  /////////////////////

  assign irq_o = error_intr || spi_event_intr;

  assign busy_o = active;

  //////////
  // CSRs //
  //////////

  spi_controller_reg spi_controller_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resp_o.aw_ready),
    .s_axil_awvalid (axil_req_i.aw_valid),
    .s_axil_awaddr  (axil_req_i.aw.addr),
    .s_axil_awprot  (axil_req_i.aw.prot),
    .s_axil_wready  (axil_resp_o.w_ready),
    .s_axil_wvalid  (axil_req_i.w_valid),
    .s_axil_wdata   (axil_req_i.w.data),
    .s_axil_wstrb   (axil_req_i.w.strb),
    .s_axil_bready  (axil_req_i.b_ready),
    .s_axil_bvalid  (axil_resp_o.b_valid),
    .s_axil_bresp   (axil_resp_o.b.resp),
    .s_axil_arready (axil_resp_o.ar_ready),
    .s_axil_arvalid (axil_req_i.ar_valid),
    .s_axil_araddr  (axil_req_i.ar.addr),
    .s_axil_arprot  (axil_req_i.ar.prot),
    .s_axil_rready  (axil_req_i.r_ready),
    .s_axil_rvalid  (axil_resp_o.r_valid),
    .s_axil_rdata   (axil_resp_o.r.data),
    .s_axil_rresp   (axil_resp_o.r.resp),

    .hwif_in        (reg_in),
    .hwif_out       (reg_out)
  );


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(paramCheckNumCs_A, NUM_CS > 0)

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(SckKnownO_A, sck_o)
  `OCAH_OT_ASSERT_KNOWN(SckEnKnownO_A, sck_en_o)
  `OCAH_OT_ASSERT_KNOWN(CsKnownO_A, cs_no)
  `OCAH_OT_ASSERT_KNOWN(CsEnKnownO_A, cs_en_o)
  `OCAH_OT_ASSERT_KNOWN(IoKnownO_A, io_o)
  `OCAH_OT_ASSERT_KNOWN(IoEnKnownO_A, io_en_o)
  `OCAH_OT_ASSERT_KNOWN(LsioTriggerKnown_A, lsio_trigger_o)
  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)

endmodule
