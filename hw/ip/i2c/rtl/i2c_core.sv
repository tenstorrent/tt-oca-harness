// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Bind I2C register outs to the controller, target, and bus-monitor FSMs.
//
// Exposes SMBus sideband, DMA ready levels, a combined irq_o, and a four-bit debug bus.
// SCL and SDA outputs are registered; the SCL, SDA, SMBus SUS and SMBus ALERT inputs are
// synchronized to clk_i.
// debug_o[0] is SDA and [1] is SCL, each sampled once by clk_i, [2] is target_idle, and [3]
// is the unextended OR of the controller error events.

module i2c_core
  import i2c_pkg::*;
#(
  parameter int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,     // Entries in the controller format
                                                            // (FMT) FIFO; 1 to 4095.
  parameter int unsigned CONTROLLER_RX_FIFO_DEPTH = 64,     // Entries in the controller receive
                                                            // (RX) FIFO; 1 to 4095.
  parameter int unsigned TARGET_TX_FIFO_DEPTH     = 64,     // Entries in the target transmit (TX)
                                                            // FIFO; 1 to 4095.
  parameter int unsigned TARGET_RX_FIFO_DEPTH     = 268,    // Entries in the target acquisition
                                                            // (ACQ) FIFO; 1 to 4095.
  parameter int unsigned INPUT_DELAY_CYCLES       = 0       // External SCL/SDA input delay in clk_i
                                                            // cycles; lengthens the
                                                            // interference-detection blanking
                                                            // window after each output change.
) (
  input                                    clk_i,           // System clock.
  input                                    rst_ni,          // Async reset, active-low.

  input  i2c_reg_pkg::i2c__out_t           reg_out_i,       // Register-block outputs into the core.
  output i2c_reg_pkg::i2c__in_t            reg_in_o,        // Register-block inputs from the core.

  input                                    scl_i,           // SCL pad input, synchronized to clk_i
                                                            // by a two-flop synchronizer.
  output logic                             scl_o,           // SCL pad output, registered AND of the
                                                            // controller and target FSM drives, or
                                                            // OVRD.SCLVAL under OVRD.TXOVRDEN; 0
                                                            // pulls the line low, 1 releases it.
  input                                    sda_i,           // SDA pad input, synchronized to clk_i
                                                            // by a two-flop synchronizer.
  output logic                             sda_o,           // SDA pad output, registered AND of the
                                                            // controller and target FSM drives, or
                                                            // OVRD.SDAVAL under OVRD.TXOVRDEN; 0
                                                            // pulls the line low, 1 releases it.

  input  logic                             smbus_en_i,      // When low, masks smbalert_ni so SMBus
                                                            // ALERT reads as deasserted.
  input  logic                             smbsus_ni,       // SMBus SUS pin in, active-low;
                                                            // synchronized and reported in
                                                            // SMBUS_STATUS.
  output logic                             smbsus_no,       // SMBus SUS pin out, active-low; driven
                                                            // from SMBUS_CTRL.SMBSUS in host mode
                                                            // without line loopback, high
                                                            // otherwise.
  input  logic                             smbalert_ni,     // SMBus ALERT pin in, active-low;
                                                            // synchronized, reported in
                                                            // SMBUS_STATUS and raises the SMBALERT
                                                            // interrupt.
  output logic                             smbalert_no,     // SMBus ALERT pin out, active-low;
                                                            // driven from SMBUS_CTRL.SMBALERT in
                                                            // target mode without loopback, high
                                                            // otherwise.

  output logic                             controller_tx_ready_o, // Controller TX DMA ready; drops
                                                                  // when the FMT FIFO fills and
                                                                  // returns once its level falls
                                                                  // below the FMT threshold.
  output logic                             controller_rx_ready_o, // Controller RX DMA ready; rises
                                                                  // when the RX level exceeds the
                                                                  // RX threshold and stays high
                                                                  // until the FIFO empties.
  output logic                             target_tx_ready_o, // Target TX DMA ready; drops when the
                                                              // TX FIFO fills and returns once its
                                                              // level falls below the TX threshold.
  output logic                             target_rx_ready_o, // Target RX DMA ready; rises when the
                                                              // ACQ level exceeds the ACQ threshold
                                                              // and stays high until the FIFO
                                                              // empties.

  output logic                             irq_o,           // Level interrupt; OR of the INTR_STATE
                                                            // sources masked by INTR_ENABLE.

  output logic [3:0]                       debug_o          // [0] SDA and [1] SCL, each sampled
                                                            // once by clk_i; [2] target_idle; [3]
                                                            // OR of the NACK, arbitration-lost,
                                                            // interference, timeout and
                                                            // SDA-unstable controller events, not
                                                            // stretched.
);

  `include "prim_assert.sv"

  // Number of bits required to represent the FIFO level/depth.
  localparam int unsigned CONTROLLER_TX_FIFO_DEPTH_W = $clog2(CONTROLLER_TX_FIFO_DEPTH + 1);
  localparam int unsigned CONTROLLER_RX_FIFO_DEPTH_W = $clog2(CONTROLLER_RX_FIFO_DEPTH + 1);
  localparam int unsigned TARGET_TX_FIFO_DEPTH_W = $clog2(TARGET_TX_FIFO_DEPTH + 1);
  localparam int unsigned TARGET_RX_FIFO_DEPTH_W = $clog2(TARGET_RX_FIFO_DEPTH + 1);

  // Maximum number of bits required to represent the level/depth of any FIFO.
  localparam int unsigned MaxFifoDepthW = 12;

  // Round-trip delay for outputs to appear on the inputs, not including rise
  // time. This is the input delay external to this IP, plus the output flop,
  // plus the 2-flop synchronizer on the input. The total value here
  // represents the minimum allowed high and low times for SCL.
  localparam int unsigned RoundTripCycles = INPUT_DELAY_CYCLES + 2 + 1;

  logic [12:0] thigh;
  logic [12:0] tlow;
  logic [12:0] t_r;
  logic [12:0] t_f;
  logic [12:0] thd_sta;
  logic [12:0] tsu_sta;
  logic [12:0] tsu_sto;
  logic [12:0] tsu_dat;
  logic [12:0] thd_dat;
  logic [12:0] t_buf;
  logic [29:0] bus_active_timeout;
  logic        stretch_timeout_enable;
  logic        bus_timeout_enable;
  logic [30:0] host_timeout;
  logic [30:0] nack_timeout;
  logic        nack_timeout_en;
  logic [30:0] host_nack_handler_timeout;
  logic        host_nack_handler_timeout_en;

  logic scl_sync;
  logic sda_sync;
  logic smbsus_n;
  logic smbalert_n;
  logic scl_out_controller_fsm, sda_out_controller_fsm;
  logic scl_out_target_fsm, sda_out_target_fsm;
  logic scl_out_fsm;
  logic sda_out_fsm;
  logic controller_transmitting;
  logic target_transmitting;

  // bus_event_detect goes low after any drive change from this IP, and it
  // returns to high once enough time has passed for the output change to
  // reach the FSMs. This is used to qualify detection of unexpected bus events,
  // where some other I2C controller or target is driving SCL or SDA
  // simultaneously.
  logic bus_event_detect;
  logic [10:0] bus_event_detect_cnt;
  logic sda_released_but_low;
  logic controller_sda_interference;
  logic target_arbitration_lost;

  logic bus_free;
  logic start_detect;
  logic stop_detect;

  // Controller
  logic event_rx_overflow;
  logic status_controller_halt;
  logic event_nak;
  logic event_unhandled_nak_timeout;
  logic event_controller_arbitration_lost;
  logic event_scl_interference;
  logic event_sda_interference;
  logic event_bus_active_timeout;
  logic event_stretch_timeout;
  logic event_sda_unstable;
  logic event_read_cmd_received;
  logic event_cmd_complete;
  logic event_controller_cmd_complete;
  // Target
  logic event_target_addr_match;
  logic event_target_cmd_complete;
  logic event_target_nack;
  logic event_tx_arbitration_lost;
  logic event_tx_bus_timeout;
  logic event_tx_stretch;
  logic event_acq_stretch;
  logic event_unexp_stop;
  logic event_host_timeout;

  logic unhandled_unexp_nak;
  logic unhandled_tx_stretch_event;
  logic target_ack_ctrl_stretching;
  logic target_ack_ctrl_sw_nack;

  // Target start/stop detection events (for TARGET_EVENTS.START_DETECT / STOP_DETECT)
  logic start_event_for_target;
  logic stop_event_for_target;

  logic [15:0] scl_rx_val;
  logic [15:0] sda_rx_val;

  logic override;

  logic                                  fmt_fifo_wvalid;
  logic                                  fmt_fifo_wready;
  logic [CONTROLLER_TX_FIFO_WIDTH-1:0]   fmt_fifo_wdata;
  logic [CONTROLLER_TX_FIFO_DEPTH_W-1:0] fmt_fifo_depth;
  logic                                  fmt_fifo_rvalid;
  logic                                  fmt_fifo_rready;
  logic [CONTROLLER_TX_FIFO_WIDTH-1:0]   fmt_fifo_rdata;
  logic [7:0]                            fmt_byte;
  logic                                  fmt_flag_start_before;
  logic                                  fmt_flag_stop_after;
  logic                                  fmt_flag_read_bytes;
  logic                                  fmt_flag_read_continue;
  logic                                  fmt_flag_nak_ok;

  logic                                  i2c_fifo_rxrst;
  logic                                  i2c_fifo_fmtrst;
  logic [MaxFifoDepthW-1:0]              i2c_fifo_rx_thresh;
  logic [MaxFifoDepthW-1:0]              i2c_fifo_fmt_thresh;

  logic                                  rx_fifo_wvalid;
  logic                                  rx_fifo_wready;
  logic [CONTROLLER_RX_FIFO_WIDTH-1:0]   rx_fifo_wdata;
  logic [CONTROLLER_RX_FIFO_DEPTH_W-1:0] rx_fifo_depth;
  logic                                  rx_fifo_rvalid;
  logic                                  rx_fifo_rready;
  logic [CONTROLLER_RX_FIFO_WIDTH-1:0]   rx_fifo_rdata;

  // FMT FIFO level below programmed threshold?
  logic                                  fmt_lt_threshold;
  // Rx FIFO level above programmed threshold?
  logic                                  rx_gt_threshold;

  logic                                  tx_fifo_wvalid;
  logic                                  tx_fifo_wready;
  logic [TARGET_TX_FIFO_WIDTH-1:0]       tx_fifo_wdata;
  logic [TARGET_TX_FIFO_DEPTH_W-1:0]     tx_fifo_depth;
  logic                                  tx_fifo_rvalid;
  logic                                  tx_fifo_rready;
  logic [TARGET_TX_FIFO_WIDTH-1:0]       tx_fifo_rdata;

  logic                                  acq_fifo_wvalid;
  logic [TARGET_RX_FIFO_WIDTH-1:0]       acq_fifo_wdata;
  logic [TARGET_RX_FIFO_DEPTH_W-1:0]     acq_fifo_depth;
  logic                                  acq_fifo_full;
  logic                                  acq_fifo_rvalid;
  logic                                  acq_fifo_rready;
  logic [TARGET_RX_FIFO_WIDTH-1:0]       acq_fifo_rdata;

  logic                                  i2c_fifo_txrst;
  logic                                  i2c_fifo_acqrst;
  logic [MaxFifoDepthW-1:0]              i2c_fifo_tx_thresh;
  logic [MaxFifoDepthW-1:0]              i2c_fifo_acq_thresh;

  // Tx FIFO level below programmed threshold?
  logic        tx_lt_threshold;
  // ACQ FIFO level above programmed threshold?
  logic        acq_gt_threshold;

  logic        host_idle;
  logic        target_idle;

  logic        host_enable;
  logic        target_enable;
  logic        line_loopback;
  logic        target_loopback;

  logic [6:0]  target_address0;
  logic [6:0]  target_mask0;
  logic [6:0]  target_address1;
  logic [6:0]  target_mask1;

  logic controller_tx_fifo_error;
  logic controller_rx_fifo_error;
  logic target_tx_fifo_error;
  logic target_rx_fifo_error;

  // Interrupt
  logic fmt_threshold_intr_test, fmt_threshold_intr_req;
  logic rx_threshold_intr_test, rx_threshold_intr_req;
  logic acq_threshold_intr_test, acq_threshold_intr_req;
  logic rx_overflow_intr_test;
  logic controller_halt_intr_test, controller_halt_intr_req;
  logic scl_interference_intr_test;
  logic sda_interference_intr_test;
  logic stretch_timeout_intr_test;
  logic sda_unstable_intr_test;
  logic cmd_complete_intr_test;
  logic tx_stretch_intr_test, tx_stretch_intr_req;
  logic tx_threshold_intr_test, tx_threshold_intr_req;
  logic acq_stretch_intr_test, acq_stretch_intr_req;
  logic unexp_stop_intr_test;
  logic host_timeout_intr_test;
  logic smbalert_intr_test;
  logic controller_tx_fifo_error_intr_test;
  logic controller_rx_fifo_error_intr_test;
  logic target_tx_fifo_error_intr_test;
  logic target_rx_fifo_error_intr_test;

  assign reg_in_o.STATUS.FMTFULL.next          = !fmt_fifo_wready;
  assign reg_in_o.STATUS.RXFULL.next           = !rx_fifo_wready;
  assign reg_in_o.STATUS.FMTEMPTY.next         = !fmt_fifo_rvalid;
  assign reg_in_o.STATUS.HOSTIDLE.next         =  host_idle;
  assign reg_in_o.STATUS.TARGETIDLE.next       =  target_idle;
  assign reg_in_o.STATUS.RXEMPTY.next          = !rx_fifo_rvalid;
  assign reg_in_o.STATUS.ACK_CTRL_STRETCH.next =  target_ack_ctrl_stretching;

  assign reg_in_o.RDATA.rd_data._reserved_31_8 = 24'h0;
  assign reg_in_o.RDATA.rd_data.DATA           = rx_fifo_rdata;
  assign reg_in_o.HOST_FIFO_STATUS.FMTLVL.next = MaxFifoDepthW'(fmt_fifo_depth);
  assign reg_in_o.HOST_FIFO_STATUS.RXLVL.next  = MaxFifoDepthW'(rx_fifo_depth);
  assign reg_in_o.VAL.SCL_RX.next              = scl_rx_val;
  assign reg_in_o.VAL.SDA_RX.next              = sda_rx_val;

  assign reg_in_o.STATUS.TXFULL.next              = !tx_fifo_wready;
  assign reg_in_o.STATUS.ACQFULL.next             =  acq_fifo_full;
  assign reg_in_o.STATUS.TXEMPTY.next             = !tx_fifo_rvalid;
  assign reg_in_o.STATUS.ACQEMPTY.next            = !acq_fifo_rvalid;
  assign reg_in_o.TARGET_FIFO_STATUS.TXLVL.next   =  MaxFifoDepthW'(tx_fifo_depth);
  assign reg_in_o.TARGET_FIFO_STATUS.ACQLVL.next  =  MaxFifoDepthW'(acq_fifo_depth);
  assign reg_in_o.ACQDATA.rd_data._reserved_31_11 = 21'h0;
  assign reg_in_o.ACQDATA.rd_data.ABYTE           =  acq_fifo_rdata[7:0];
  assign reg_in_o.ACQDATA.rd_data.SIGNAL          =  acq_fifo_rdata[TARGET_RX_FIFO_WIDTH-1:8];

  // Add one to the target NACK count if this target has sent a NACK and if
  // counter has not saturated.
  assign reg_in_o.TARGET_NACK_COUNT.TARGET_NACK_COUNT.incr = event_target_nack;

  assign override = reg_out_i.OVRD.TXOVRDEN.value;

  assign scl_o = override ? reg_out_i.OVRD.SCLVAL.value : scl_out_fsm;
  assign sda_o = override ? reg_out_i.OVRD.SDAVAL.value : sda_out_fsm;

  assign host_enable   = reg_out_i.CTRL.ENABLEHOST.value;
  assign target_enable = reg_out_i.CTRL.ENABLETARGET.value;
  assign line_loopback = reg_out_i.CTRL.LLPBK.value;

  assign event_cmd_complete = event_controller_cmd_complete || event_target_cmd_complete;

  // Target loopback simply plays back whatever is received from the external host
  // back to it.
  assign target_loopback = target_enable && line_loopback;

  assign target_address0 = reg_out_i.TARGET_ID.ADDRESS0.value;
  assign target_mask0    = reg_out_i.TARGET_ID.MASK0.value;
  assign target_address1 = reg_out_i.TARGET_ID.ADDRESS1.value;
  assign target_mask1    = reg_out_i.TARGET_ID.MASK1.value;

  // Flop I2C bus outputs
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      scl_out_fsm <= 1'b1;
      sda_out_fsm <= 1'b1;
    end else begin
      // Drive 0 if any FSM requests it.
      scl_out_fsm <= scl_out_controller_fsm & scl_out_target_fsm;
      sda_out_fsm <= sda_out_controller_fsm & sda_out_target_fsm;
    end
  end

  // Sample scl_i and sda_i at system clock
  always_ff @(posedge clk_i or negedge rst_ni) begin : rx_oversampling
    if (~rst_ni) begin
      scl_rx_val <= 16'h0;
      sda_rx_val <= 16'h0;
    end else begin
      scl_rx_val <= {scl_rx_val[14:0], scl_i};
      sda_rx_val <= {sda_rx_val[14:0], sda_i};
    end
  end

  assign thigh   =     reg_out_i.TIMING0.THIGH.value;
  assign tlow    =     reg_out_i.TIMING0.TLOW.value;
  assign t_r     = 13'(reg_out_i.TIMING1.T_R.value);
  assign t_f     = 13'(reg_out_i.TIMING1.T_F.value);
  assign tsu_sta =     reg_out_i.TIMING2.TSU_STA.value;
  assign thd_sta =     reg_out_i.TIMING2.THD_STA.value;
  assign tsu_dat = 13'(reg_out_i.TIMING3.TSU_DAT.value);
  assign thd_dat =     reg_out_i.TIMING3.THD_DAT.value;
  assign tsu_sto =     reg_out_i.TIMING4.TSU_STO.value;
  assign t_buf   =     reg_out_i.TIMING4.T_BUF.value;

  assign bus_active_timeout           = reg_out_i.TIMEOUT_CTRL.VAL.value;
  assign stretch_timeout_enable       = reg_out_i.TIMEOUT_CTRL.EN.value &&
                                          reg_out_i.TIMEOUT_CTRL.MODE.value == StretchTimeoutMode;
  assign bus_timeout_enable           = reg_out_i.TIMEOUT_CTRL.EN.value &&
                                          reg_out_i.TIMEOUT_CTRL.MODE.value == BusTimeoutMode;
  assign host_timeout                 = reg_out_i.HOST_TIMEOUT_CTRL.VAL.value;
  assign nack_timeout                 = reg_out_i.TARGET_TIMEOUT_CTRL.VAL.value;
  assign nack_timeout_en              = reg_out_i.TARGET_TIMEOUT_CTRL.EN.value;
  assign host_nack_handler_timeout    = reg_out_i.HOST_NACK_HANDLER_TIMEOUT.VAL.value;
  assign host_nack_handler_timeout_en = reg_out_i.HOST_NACK_HANDLER_TIMEOUT.EN.value;
  assign target_ack_ctrl_sw_nack      = reg_out_i.TARGET_ACK_CTRL.NACK.value;

  assign i2c_fifo_rxrst      = reg_out_i.FIFO_CTRL.RXRST.value;
  assign i2c_fifo_fmtrst     = reg_out_i.FIFO_CTRL.FMTRST.value;
  assign i2c_fifo_rx_thresh  = reg_out_i.HOST_FIFO_CONFIG.RX_THRESH.value;
  assign i2c_fifo_fmt_thresh = reg_out_i.HOST_FIFO_CONFIG.FMT_THRESH.value;

  assign i2c_fifo_txrst      = reg_out_i.FIFO_CTRL.TXRST.value;
  assign i2c_fifo_acqrst     = reg_out_i.FIFO_CTRL.ACQRST.value;
  assign i2c_fifo_tx_thresh  = reg_out_i.TARGET_FIFO_CONFIG.TX_THRESH.value;
  assign i2c_fifo_acq_thresh = reg_out_i.TARGET_FIFO_CONFIG.ACQ_THRESH.value;

  // FMT FIFO level below programmed threshold?
  assign fmt_lt_threshold = MaxFifoDepthW'(fmt_fifo_depth) < i2c_fifo_fmt_thresh;
  // Rx FIFO level above programmed threshold?
  assign rx_gt_threshold  = MaxFifoDepthW'(rx_fifo_depth)  > i2c_fifo_rx_thresh;
  // Tx FIFO level below programmed threshold?
  assign tx_lt_threshold  = MaxFifoDepthW'(tx_fifo_depth)  < i2c_fifo_tx_thresh;
  // ACQ FIFO level above programmed threshold?
  assign acq_gt_threshold = MaxFifoDepthW'(acq_fifo_depth) > i2c_fifo_acq_thresh;

  assign event_rx_overflow = rx_fifo_wvalid && !rx_fifo_wready;
  assign event_acq_stretch = acq_fifo_full || target_ack_ctrl_stretching;

  // The fifo write enable is controlled by fbyte, start, stop, read, rcont,
  // and nakok field qe bits.
  // When all qe bits are asserted, fdata is injected into the fifo.
  assign reg_in_o.FDATA.wr_ack = reg_out_i.FDATA.req && reg_out_i.FDATA.req_is_wr;
  assign fmt_fifo_wvalid       = reg_out_i.FDATA.req && reg_out_i.FDATA.req_is_wr &&
                                   |reg_out_i.FDATA.wr_biten;
  assign fmt_fifo_wdata[7:0]   = reg_out_i.FDATA.wr_data.FBYTE  & reg_out_i.FDATA.wr_biten.FBYTE;
  assign fmt_fifo_wdata[8]     = reg_out_i.FDATA.wr_data.START && reg_out_i.FDATA.wr_biten.START;
  assign fmt_fifo_wdata[9]     = reg_out_i.FDATA.wr_data.STOP  && reg_out_i.FDATA.wr_biten.STOP;
  assign fmt_fifo_wdata[10]    = reg_out_i.FDATA.wr_data.READB && reg_out_i.FDATA.wr_biten.READB;
  assign fmt_fifo_wdata[11]    = reg_out_i.FDATA.wr_data.RCONT && reg_out_i.FDATA.wr_biten.RCONT;
  assign fmt_fifo_wdata[12]    = reg_out_i.FDATA.wr_data.NAKOK && reg_out_i.FDATA.wr_biten.NAKOK;

  assign fmt_byte               = fmt_fifo_rvalid ? fmt_fifo_rdata[7:0] : 8'h0;
  assign fmt_flag_start_before  = fmt_fifo_rvalid ? fmt_fifo_rdata[8]   : 1'b0;
  assign fmt_flag_stop_after    = fmt_fifo_rvalid ? fmt_fifo_rdata[9]   : 1'b0;
  assign fmt_flag_read_bytes    = fmt_fifo_rvalid ? fmt_fifo_rdata[10]  : 1'b0;
  assign fmt_flag_read_continue = fmt_fifo_rvalid ? fmt_fifo_rdata[11]  : 1'b0;
  assign fmt_flag_nak_ok        = fmt_fifo_rvalid ? fmt_fifo_rdata[12]  : 1'b0;

  // Operating this HWIP as a controller-transmitter, the addressed Target device
  // may NACK our bytes. In Byte-Formatted Programming Mode, each FDATA format indicator
  // can set the 'NAKOK' bit to ignore the Target's NACK and proceed to the next item in
  // the FMTFIFO. If 'NAKOK' is not set, the 'controller_halt' interrupt is asserted, and the FSM
  // halts until software intervenes. In addition, the 'CONTROLLER_EVENTS.NACK' status bit is set.
  // To acknowledge the 'NACK', software should clear the status bit by writing 1 to it in the
  // CONTROLLER_EVENTS register.
  assign unhandled_unexp_nak = reg_out_i.CONTROLLER_EVENTS.NACK.value;

  prim_fifo_sync_parity #(
    .Width             (CONTROLLER_TX_FIFO_WIDTH),
    .Pass              (1'b1),
    .Depth             (CONTROLLER_TX_FIFO_DEPTH),
    .OutputZeroIfEmpty (1'b1),
    .NeverClears       (1'b0),
    .Secure            (1'b1)
  ) u_controller_tx_fifo (
    .clk_i,
    .rst_ni,
    .clr_i             (i2c_fifo_fmtrst),
    .wvalid_i          (fmt_fifo_wvalid),
    .wready_o          (fmt_fifo_wready),
    .wdata_i           (fmt_fifo_wdata),
    .rvalid_o          (fmt_fifo_rvalid),
    .rready_i          (fmt_fifo_rready),
    .rdata_o           (fmt_fifo_rdata),
    .full_o            (/* UNUSED */),
    .depth_o           (fmt_fifo_depth),
    .err_o             (controller_tx_fifo_error)
  );

  prim_fifo_sync_parity #(
    .Width             (CONTROLLER_RX_FIFO_WIDTH),
    .Pass              (1'b1),
    .Depth             (CONTROLLER_RX_FIFO_DEPTH),
    .OutputZeroIfEmpty (1'b1),
    .NeverClears       (1'b0),
    .Secure            (1'b1)
  ) u_controller_rx_fifo (
    .clk_i,
    .rst_ni,
    .clr_i             (i2c_fifo_rxrst),
    .wvalid_i          (rx_fifo_wvalid),
    .wready_o          (rx_fifo_wready),
    .wdata_i           (rx_fifo_wdata),
    .rvalid_o          (rx_fifo_rvalid),
    .rready_i          (rx_fifo_rready),
    .rdata_o           (rx_fifo_rdata),
    .full_o            (/* UNUSED */),
    .depth_o           (rx_fifo_depth),
    .err_o             (controller_rx_fifo_error)
  );

  prim_fifo_sync_parity #(
    .Width             (TARGET_TX_FIFO_WIDTH),
    .Pass              (1'b1),
    .Depth             (TARGET_TX_FIFO_DEPTH),
    .OutputZeroIfEmpty (1'b1),
    .NeverClears       (1'b0),
    .Secure            (1'b1)
  ) u_target_tx_fifo (
    .clk_i,
    .rst_ni,
    .clr_i             (i2c_fifo_txrst),
    .wvalid_i          (tx_fifo_wvalid),
    .wready_o          (tx_fifo_wready),
    .wdata_i           (tx_fifo_wdata),
    .rvalid_o          (tx_fifo_rvalid),
    .rready_i          (tx_fifo_rready),
    .rdata_o           (tx_fifo_rdata),
    .full_o            (/* UNUSED */),
    .depth_o           (tx_fifo_depth),
    .err_o             (target_tx_fifo_error)
  );

  prim_fifo_sync_parity #(
    .Width             (TARGET_RX_FIFO_WIDTH),
    .Pass              (1'b1),
    .Depth             (TARGET_RX_FIFO_DEPTH),
    .OutputZeroIfEmpty (1'b1),
    .NeverClears       (1'b0),
    .Secure            (1'b1)
  ) u_target_rx_fifo (
    .clk_i,
    .rst_ni,
    .clr_i             (i2c_fifo_acqrst),
    .wvalid_i          (acq_fifo_wvalid),
    .wready_o          (/* UNUSED */),
    .wdata_i           (acq_fifo_wdata),
    .rvalid_o          (acq_fifo_rvalid),
    .rready_i          (acq_fifo_rready),
    .rdata_o           (acq_fifo_rdata),
    .full_o            (/* UNUSED */),
    .depth_o           (acq_fifo_depth),
    .err_o             (target_rx_fifo_error)
  );

  prim_alert_pkg::alert_tx_t unused_alert_tx;

  prim_alert_sender #(
    .AsyncOn       (1'b1),
    .IsFatal       (1'b0)
  ) u_prim_alert_sender (
    .clk_i,
    .rst_ni,
    .alert_test_i  (1'b0),
    .alert_req_i   (controller_tx_fifo_error ||
                        controller_rx_fifo_error ||
                        target_tx_fifo_error ||
                        target_rx_fifo_error),
    .alert_ack_o   (/* UNUSED */),
    .alert_state_o (/* UNUSED */),
    .alert_rx_i    (prim_alert_pkg::ALERT_RX_DEFAULT),
    .alert_tx_o    (unused_alert_tx)
  );

  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      ControllerTxFifoWptrErrTriggerAlert_A,
      u_controller_tx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_wptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      ControllerTxFifoRptrErrTriggerAlert_A,
      u_controller_tx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_rptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      ControllerRxFifoWptrErrTriggerAlert_A,
      u_controller_rx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_wptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      ControllerRxFifoRptrErrTriggerAlert_A,
      u_controller_rx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_rptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      TargetTxFifoWptrErrTriggerAlert_A,
      u_target_tx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_wptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      TargetTxFifoRptrErrTriggerAlert_A,
      u_target_tx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_rptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      TargetRxFifoWptrErrTriggerAlert_A,
      u_target_rx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_wptr, unused_alert_tx)
  `OCAH_OT_ASSERT_PRIM_COUNT_ERROR_TRIGGER_ALERT(
      TargetRxFifoRptrErrTriggerAlert_A,
      u_target_rx_fifo.gen_normal_fifo.u_fifo_cnt.gen_secure_ptrs.u_rptr, unused_alert_tx)

  assign reg_in_o.RDATA.rd_ack = reg_out_i.RDATA.req && !reg_out_i.RDATA.req_is_wr;
  assign rx_fifo_rready        = reg_out_i.RDATA.req && !reg_out_i.RDATA.req_is_wr;

  // Need to add a valid qualification to write only payload bytes
  logic             valid_target_lb_wr;
  i2c_acq_byte_id_e acq_type;

  assign acq_type = i2c_acq_byte_id_e'(acq_fifo_rdata[TARGET_RX_FIFO_WIDTH-1:8]);

  assign valid_target_lb_wr = target_enable && acq_type == AcqData;

  // only write into tx fifo if it's payload
  assign reg_in_o.TXDATA.wr_ack = reg_out_i.TXDATA.req && reg_out_i.TXDATA.req_is_wr;
  assign tx_fifo_wvalid         = target_loopback ? acq_fifo_rvalid && valid_target_lb_wr :
                                                       reg_out_i.TXDATA.req &&
                                                       reg_out_i.TXDATA.req_is_wr &&
                                                      |reg_out_i.TXDATA.wr_biten;
  assign tx_fifo_wdata          = target_loopback ? acq_fifo_rdata[7:0] :
                                                      reg_out_i.TXDATA.wr_data.DATA;

  // During line loopback, pop from acquisition fifo only when there is space in
  // the tx_fifo.  We are also allowed to pop even if there is no space if th acq entry
  // is not data payload.
  assign reg_in_o.ACQDATA.rd_ack = reg_out_i.ACQDATA.req && !reg_out_i.ACQDATA.req_is_wr;
  assign acq_fifo_rready         = reg_out_i.ACQDATA.req && !reg_out_i.ACQDATA.req_is_wr ||
                                     target_loopback && (tx_fifo_wready || acq_type != AcqData);

  // sync the incoming SCL and SDA signals
  prim_flop_2sync #(
    .Width      (1),
    .ResetValue (1'b1)
  ) u_i2c_sync_scl (
    .clk_i,
    .rst_ni,
    .d_i        (scl_i),
    .q_o        (scl_sync)
  );

  prim_flop_2sync #(
    .Width      (1),
    .ResetValue (1'b1)
  ) u_i2c_sync_sda (
    .clk_i,
    .rst_ni,
    .d_i        (sda_i),
    .q_o        (sda_sync)
  );

  // Various bus collision events are detected while SCL is high.
  logic sda_fsm, sda_fsm_q;
  logic scl_fsm, scl_fsm_q;

  assign sda_fsm = sda_out_controller_fsm & sda_out_target_fsm;
  assign scl_fsm = scl_out_controller_fsm & scl_out_target_fsm;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      sda_fsm_q <= 1'b1;
      scl_fsm_q <= 1'b1;
    end else begin
      sda_fsm_q <= sda_fsm;
      scl_fsm_q <= scl_fsm;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      bus_event_detect_cnt <= '1;
    end else if (scl_fsm != scl_fsm_q || sda_fsm != sda_fsm_q) begin
      // Wait for the round-trip time on SCL changes or on SDA changes. The
      // latter handles Start and Stop conditions, so changes while SCL is high
      // are allowed to propagate. The rise time is used here because it
      // should be the longer value. The (-1) term here is to account for the
      // delay in the counter.
      // Note that there are limits to this method of detecting arbitration.
      // A separate, buggy device that drives clock low faster than the counter
      // can expire would not trigger loss of arbitration.
      bus_event_detect_cnt <= reg_out_i.TIMING1.T_R.value + 10'(RoundTripCycles - 1);
    end else if (bus_event_detect_cnt != '0) begin
      bus_event_detect_cnt <= bus_event_detect_cnt - 1'b1;
    end
  end

  assign bus_event_detect = bus_event_detect_cnt == '0;
  assign sda_released_but_low = bus_event_detect && scl_sync && sda_fsm_q != sda_sync;
  // What about unexpected start / stop on the bits that are read?
  assign controller_sda_interference = controller_transmitting && sda_released_but_low;
  assign target_arbitration_lost = target_transmitting && sda_released_but_low;

  assign event_sda_interference = controller_sda_interference;

  // The bus monitor detects starts, stops, and bus timeouts. It also reports
  // when the bus is free for the controller to transmit.
  i2c_bus_monitor u_i2c_bus_monitor (
    .clk_i,
    .rst_ni,

    .scl_i                      (scl_sync),
    .sda_i                      (sda_sync),

    .controller_enable_i        (host_enable),
    .multi_controller_enable_i  (reg_out_i.CTRL.MULTI_CONTROLLER_MONITOR_EN.value),
    .target_enable_i            (target_enable),
    .target_idle_i              (target_idle),
    .thd_dat_i                  (thd_dat),
    .t_buf_i                    (t_buf),
    .bus_active_timeout_i       (bus_active_timeout),
    .bus_active_timeout_en_i    (bus_timeout_enable),
    .bus_inactive_timeout_i     (host_timeout),

    .bus_free_o                 (bus_free),
    .start_detect_o             (start_detect),
    .stop_detect_o              (stop_detect),

    .event_bus_active_timeout_o (event_bus_active_timeout),
    .event_host_timeout_o       (event_host_timeout)
  );

  // Target start/stop events: qualify global bus monitor events with target_enable
  // to form sticky W1C flags in TARGET_EVENTS.
  assign start_event_for_target = target_enable && start_detect;
  assign stop_event_for_target  = target_enable && stop_detect;

  i2c_controller_fsm #(
    .CONTROLLER_TX_FIFO_DEPTH(CONTROLLER_TX_FIFO_DEPTH)
  ) u_i2c_controller_fsm (
    .clk_i,
    .rst_ni,

    .scl_i                          (scl_sync),
    .scl_o                          (scl_out_controller_fsm),
    .sda_i                          (sda_sync),
    .sda_o                          (sda_out_controller_fsm),
    .bus_free_i                     (bus_free),
    .transmitting_o                 (controller_transmitting),

    .host_enable_i                  (host_enable),
    .halt_controller_i              (status_controller_halt),

    .fmt_fifo_rvalid_i              (fmt_fifo_rvalid),
    .fmt_fifo_depth_i               (fmt_fifo_depth),
    .fmt_fifo_rready_o              (fmt_fifo_rready),

    .fmt_byte_i                     (fmt_byte),
    .fmt_flag_start_before_i        (fmt_flag_start_before),
    .fmt_flag_stop_after_i          (fmt_flag_stop_after),
    .fmt_flag_read_bytes_i          (fmt_flag_read_bytes),
    .fmt_flag_read_continue_i       (fmt_flag_read_continue),
    .fmt_flag_nak_ok_i              (fmt_flag_nak_ok),
    .unhandled_unexp_nak_i          (unhandled_unexp_nak),
    .unhandled_nak_timeout_i        (reg_out_i.CONTROLLER_EVENTS.UNHANDLED_NACK_TIMEOUT.value),

    .rx_fifo_wvalid_o               (rx_fifo_wvalid),
    .rx_fifo_wdata_o                (rx_fifo_wdata),

    .host_idle_o                    (host_idle),

    .thigh_i                        (thigh),
    .tlow_i                         (tlow),
    .t_r_i                          (t_r),
    .t_f_i                          (t_f),
    .thd_sta_i                      (thd_sta),
    .tsu_sta_i                      (tsu_sta),
    .tsu_sto_i                      (tsu_sto),
    .thd_dat_i                      (thd_dat),
    .sda_interference_i             (controller_sda_interference),
    .stretch_timeout_i              (bus_active_timeout),
    .timeout_enable_i               (stretch_timeout_enable),
    .host_nack_handler_timeout_i    (host_nack_handler_timeout),
    .host_nack_handler_timeout_en_i (host_nack_handler_timeout_en),
    .event_nak_o                    (event_nak),
    .event_unhandled_nak_timeout_o  (event_unhandled_nak_timeout),
    .event_arbitration_lost_o       (event_controller_arbitration_lost),
    .event_scl_interference_o       (event_scl_interference),
    .event_stretch_timeout_o        (event_stretch_timeout),
    .event_sda_unstable_o           (event_sda_unstable),
    .event_cmd_complete_o           (event_controller_cmd_complete)
  );

  i2c_target_fsm #(
    .TARGET_RX_FIFO_DEPTH(TARGET_RX_FIFO_DEPTH)
  ) u_i2c_target_fsm (
    .clk_i,
    .rst_ni,

    .scl_i                        (scl_sync),
    .scl_o                        (scl_out_target_fsm),
    .sda_i                        (sda_sync),
    .sda_o                        (sda_out_target_fsm),
    .start_detect_i               (start_detect),
    .stop_detect_i                (stop_detect),
    .transmitting_o               (target_transmitting),

    .target_enable_i              (target_enable),

    .tx_fifo_rvalid_i             (tx_fifo_rvalid),
    .tx_fifo_rready_o             (tx_fifo_rready),
    .tx_fifo_rdata_i              (tx_fifo_rdata),

    .acq_fifo_wvalid_o            (acq_fifo_wvalid),
    .acq_fifo_wdata_o             (acq_fifo_wdata),
    .acq_fifo_rdata_i             (acq_fifo_rdata),
    .acq_fifo_full_o              (acq_fifo_full),
    .acq_fifo_depth_i             (acq_fifo_depth),

    .target_idle_o                (target_idle),

    .t_r_i                        (t_r),
    .tsu_dat_i                    (tsu_dat),
    .thd_dat_i                    (thd_dat),
    .nack_timeout_i               (nack_timeout),
    .nack_timeout_en_i            (nack_timeout_en),
    .nack_addr_after_timeout_i    (reg_out_i.CTRL.NACK_ADDR_AFTER_TIMEOUT.value),
    .arbitration_lost_i           (target_arbitration_lost),
    .bus_timeout_i                (event_bus_active_timeout),
    .unhandled_tx_stretch_event_i (unhandled_tx_stretch_event),
    .ack_ctrl_mode_i              (reg_out_i.CTRL.ACK_CTRL_EN.value),
    .acq_start_stop_en_i           (reg_out_i.CTRL.ACQ_START_STOP_EN.value),
    .auto_ack_cnt_i               (reg_out_i.TARGET_ACK_CTRL.NBYTES.value),
    .auto_ack_cnt_clr_o           (reg_in_o.TARGET_ACK_CTRL.NBYTES.hwclr),
    .auto_ack_cnt_decr_o          (reg_in_o.TARGET_ACK_CTRL.NBYTES.decr),
    .sw_nack_i                    (target_ack_ctrl_sw_nack),
    .ack_ctrl_stretching_o        (target_ack_ctrl_stretching),
    .acq_fifo_next_data_o         (reg_in_o.ACQ_FIFO_NEXT_DATA.DATA.next),
    .target_address0_i            (target_address0),
    .target_mask0_i               (target_mask0),
    .target_address1_i            (target_address1),
    .target_mask1_i               (target_mask1),
    .event_address_match_o        (event_target_addr_match),
    .event_target_nack_o          (event_target_nack),
    .event_read_cmd_received_o    (event_read_cmd_received),
    .event_cmd_complete_o         (event_target_cmd_complete),
    .event_tx_stretch_o           (event_tx_stretch),
    .event_unexp_stop_o           (event_unexp_stop),
    .event_tx_arbitration_lost_o  (event_tx_arbitration_lost),
    .event_tx_bus_timeout_o       (event_tx_bus_timeout)
  );

  assign reg_in_o.TARGET_ACK_CTRL.NBYTES.swwe = target_ack_ctrl_stretching;


  ///////////////
  // DMA Logic //
  ///////////////

  typedef enum logic {
    ST_CONTROLLER_DMA_TX_IDLE      = 1'd0,
    ST_CONTROLLER_DMA_TX_NOT_READY = 1'd1
  } controller_dma_tx_fsm_state_e;

  controller_dma_tx_fsm_state_e controller_dma_tx_fsm_state, controller_dma_tx_fsm_state_next;

  always_comb begin
    controller_tx_ready_o = 1'b0;
    controller_dma_tx_fsm_state_next = controller_dma_tx_fsm_state;

    unique case (controller_dma_tx_fsm_state)
      ST_CONTROLLER_DMA_TX_IDLE: begin
        if (fmt_fifo_depth == CONTROLLER_TX_FIFO_DEPTH_W'(CONTROLLER_TX_FIFO_DEPTH)) begin
          controller_tx_ready_o = 1'b0;
          controller_dma_tx_fsm_state_next = ST_CONTROLLER_DMA_TX_NOT_READY;
        end else begin
          controller_tx_ready_o = 1'b1;
          controller_dma_tx_fsm_state_next = ST_CONTROLLER_DMA_TX_IDLE;
        end
      end
      ST_CONTROLLER_DMA_TX_NOT_READY: begin
        if (fmt_lt_threshold) begin
          controller_tx_ready_o = 1'b1;
          controller_dma_tx_fsm_state_next = ST_CONTROLLER_DMA_TX_IDLE;
        end else begin
          controller_tx_ready_o = 1'b0;
          controller_dma_tx_fsm_state_next = ST_CONTROLLER_DMA_TX_NOT_READY;
        end
      end
      default: begin
        controller_tx_ready_o = 1'b0;
        controller_dma_tx_fsm_state_next = ST_CONTROLLER_DMA_TX_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      controller_dma_tx_fsm_state <= ST_CONTROLLER_DMA_TX_IDLE;
    end else begin
      controller_dma_tx_fsm_state <= controller_dma_tx_fsm_state_next;
    end
  end

  typedef enum logic {
    ST_CONTROLLER_DMA_RX_IDLE  = 1'd0,
    ST_CONTROLLER_DMA_RX_READY = 1'd1
  } controller_dma_rx_fsm_state_e;

  controller_dma_rx_fsm_state_e controller_dma_rx_fsm_state, controller_dma_rx_fsm_state_next;

  always_comb begin
    controller_rx_ready_o = 1'b0;
    controller_dma_rx_fsm_state_next = controller_dma_rx_fsm_state;

    unique case (controller_dma_rx_fsm_state)
      ST_CONTROLLER_DMA_RX_IDLE: begin
        if (rx_gt_threshold) begin
          controller_rx_ready_o = 1'b1;
          controller_dma_rx_fsm_state_next = ST_CONTROLLER_DMA_RX_READY;
        end else begin
          controller_rx_ready_o = 1'b0;
          controller_dma_rx_fsm_state_next = ST_CONTROLLER_DMA_RX_IDLE;
        end
      end
      ST_CONTROLLER_DMA_RX_READY: begin
        if (rx_fifo_depth == CONTROLLER_RX_FIFO_DEPTH_W'(0)) begin
          controller_rx_ready_o = 1'b0;
          controller_dma_rx_fsm_state_next = ST_CONTROLLER_DMA_RX_IDLE;
        end else begin
          controller_rx_ready_o = 1'b1;
          controller_dma_rx_fsm_state_next = ST_CONTROLLER_DMA_RX_READY;
        end
      end
      default: begin
        controller_rx_ready_o = 1'b0;
        controller_dma_rx_fsm_state_next = ST_CONTROLLER_DMA_RX_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      controller_dma_rx_fsm_state <= ST_CONTROLLER_DMA_RX_IDLE;
    end else begin
      controller_dma_rx_fsm_state <= controller_dma_rx_fsm_state_next;
    end
  end

  typedef enum logic {
    ST_TARGET_DMA_TX_IDLE      = 1'd0,
    ST_TARGET_DMA_TX_NOT_READY = 1'd1
  } target_dma_tx_fsm_state_e;

  target_dma_tx_fsm_state_e target_dma_tx_fsm_state, target_dma_tx_fsm_state_next;

  always_comb begin
    target_tx_ready_o = 1'b0;
    target_dma_tx_fsm_state_next = target_dma_tx_fsm_state;

    unique case (target_dma_tx_fsm_state)
      ST_TARGET_DMA_TX_IDLE: begin
        if (tx_fifo_depth == TARGET_TX_FIFO_DEPTH_W'(TARGET_TX_FIFO_DEPTH)) begin
          target_tx_ready_o = 1'b0;
          target_dma_tx_fsm_state_next = ST_TARGET_DMA_TX_NOT_READY;
        end else begin
          target_tx_ready_o = 1'b1;
          target_dma_tx_fsm_state_next = ST_TARGET_DMA_TX_IDLE;
        end
      end
      ST_TARGET_DMA_TX_NOT_READY: begin
        if (tx_lt_threshold) begin
          target_tx_ready_o = 1'b1;
          target_dma_tx_fsm_state_next = ST_TARGET_DMA_TX_IDLE;
        end else begin
          target_tx_ready_o = 1'b0;
          target_dma_tx_fsm_state_next = ST_TARGET_DMA_TX_NOT_READY;
        end
      end
      default: begin
        target_tx_ready_o = 1'b0;
        target_dma_tx_fsm_state_next = ST_TARGET_DMA_TX_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      target_dma_tx_fsm_state <= ST_TARGET_DMA_TX_IDLE;
    end else begin
      target_dma_tx_fsm_state <= target_dma_tx_fsm_state_next;
    end
  end

  typedef enum logic {
    ST_TARGET_DMA_RX_IDLE  = 1'd0,
    ST_TARGET_DMA_RX_READY = 1'd1
  } target_dma_rx_fsm_state_e;

  target_dma_rx_fsm_state_e target_dma_rx_fsm_state, target_dma_rx_fsm_state_next;

  always_comb begin
    target_rx_ready_o = 1'b0;
    target_dma_rx_fsm_state_next = target_dma_rx_fsm_state;

    unique case (target_dma_rx_fsm_state)
      ST_TARGET_DMA_RX_IDLE: begin
        if (acq_gt_threshold) begin
          target_rx_ready_o = 1'b1;
          target_dma_rx_fsm_state_next = ST_TARGET_DMA_RX_READY;
        end else begin
          target_rx_ready_o = 1'b0;
          target_dma_rx_fsm_state_next = ST_TARGET_DMA_RX_IDLE;
        end
      end
      ST_TARGET_DMA_RX_READY: begin
        if (acq_fifo_depth == TARGET_RX_FIFO_DEPTH_W'(0)) begin
          target_rx_ready_o = 1'b0;
          target_dma_rx_fsm_state_next = ST_TARGET_DMA_RX_IDLE;
        end else begin
          target_rx_ready_o = 1'b1;
          target_dma_rx_fsm_state_next = ST_TARGET_DMA_RX_READY;
        end
      end
      default: begin
        target_rx_ready_o = 1'b0;
        target_dma_rx_fsm_state_next = ST_TARGET_DMA_RX_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      target_dma_rx_fsm_state <= ST_TARGET_DMA_RX_IDLE;
    end else begin
      target_dma_rx_fsm_state <= target_dma_rx_fsm_state_next;
    end
  end


  /////////////////////
  // Interrupt Logic //
  /////////////////////

  assign fmt_threshold_intr_req   = fmt_lt_threshold || fmt_threshold_intr_test;
  assign rx_threshold_intr_req    = rx_gt_threshold || rx_threshold_intr_test;
  assign acq_threshold_intr_req   = acq_gt_threshold || acq_threshold_intr_test;
  assign controller_halt_intr_req = status_controller_halt || controller_halt_intr_test;
  assign tx_stretch_intr_req      = event_tx_stretch || tx_stretch_intr_test;
  assign tx_threshold_intr_req    = tx_lt_threshold || tx_threshold_intr_test;
  assign acq_stretch_intr_req     = event_acq_stretch || acq_stretch_intr_test;

  // Event-type status bits latch whether or not the interrupt is enabled
  // Clear only on W1C; INTR_ENABLE masks the output
  assign irq_o =
        (reg_out_i.INTR_STATE.RX_OVERFLOW.value              && reg_out_i.INTR_ENABLE.RX_OVERFLOW.value) ||
        (reg_out_i.INTR_STATE.SCL_INTERFERENCE.value         && reg_out_i.INTR_ENABLE.SCL_INTERFERENCE.value) ||
        (reg_out_i.INTR_STATE.SDA_INTERFERENCE.value         && reg_out_i.INTR_ENABLE.SDA_INTERFERENCE.value) ||
        (reg_out_i.INTR_STATE.STRETCH_TIMEOUT.value          && reg_out_i.INTR_ENABLE.STRETCH_TIMEOUT.value) ||
        (reg_out_i.INTR_STATE.SDA_UNSTABLE.value             && reg_out_i.INTR_ENABLE.SDA_UNSTABLE.value) ||
        (reg_out_i.INTR_STATE.CMD_COMPLETE.value             && reg_out_i.INTR_ENABLE.CMD_COMPLETE.value) ||
        (reg_out_i.INTR_STATE.UNEXP_STOP.value               && reg_out_i.INTR_ENABLE.UNEXP_STOP.value) ||
        (reg_out_i.INTR_STATE.HOST_TIMEOUT.value             && reg_out_i.INTR_ENABLE.HOST_TIMEOUT.value) ||
        (reg_out_i.INTR_STATE.SMBALERT.value                 && reg_out_i.INTR_ENABLE.SMBALERT.value) ||
        (reg_out_i.INTR_STATE.CONTROLLER_TX_FIFO_ERROR.value && reg_out_i.INTR_ENABLE.CONTROLLER_TX_FIFO_ERROR.value) ||
        (reg_out_i.INTR_STATE.CONTROLLER_RX_FIFO_ERROR.value && reg_out_i.INTR_ENABLE.CONTROLLER_RX_FIFO_ERROR.value) ||
        (reg_out_i.INTR_STATE.TARGET_TX_FIFO_ERROR.value     && reg_out_i.INTR_ENABLE.TARGET_TX_FIFO_ERROR.value) ||
        (reg_out_i.INTR_STATE.TARGET_RX_FIFO_ERROR.value     && reg_out_i.INTR_ENABLE.TARGET_RX_FIFO_ERROR.value) ||
        (fmt_threshold_intr_req                              && reg_out_i.INTR_ENABLE.FMT_THRESHOLD.value) ||
        (rx_threshold_intr_req                               && reg_out_i.INTR_ENABLE.RX_THRESHOLD.value) ||
        (acq_threshold_intr_req                              && reg_out_i.INTR_ENABLE.ACQ_THRESHOLD.value) ||
        (controller_halt_intr_req                            && reg_out_i.INTR_ENABLE.CONTROLLER_HALT.value) ||
        (tx_stretch_intr_req                                 && reg_out_i.INTR_ENABLE.TX_STRETCH.value) ||
        (tx_threshold_intr_req                               && reg_out_i.INTR_ENABLE.TX_THRESHOLD.value) ||
        (acq_stretch_intr_req                                && reg_out_i.INTR_ENABLE.ACQ_STRETCH.value);


  ///////////////
  // CSR Logic //
  ///////////////

  // INTR_STATE Register
  assign reg_in_o.INTR_STATE.FMT_THRESHOLD.next            = fmt_threshold_intr_req;
  assign reg_in_o.INTR_STATE.RX_THRESHOLD.next             = rx_threshold_intr_req;
  assign reg_in_o.INTR_STATE.ACQ_THRESHOLD.next            = acq_threshold_intr_req;
  assign reg_in_o.INTR_STATE.RX_OVERFLOW.next              = event_rx_overflow || rx_overflow_intr_test;
  assign reg_in_o.INTR_STATE.CONTROLLER_HALT.next          = controller_halt_intr_req;
  assign reg_in_o.INTR_STATE.SCL_INTERFERENCE.next         = event_scl_interference || scl_interference_intr_test;
  assign reg_in_o.INTR_STATE.SDA_INTERFERENCE.next         = event_sda_interference || sda_interference_intr_test;
  assign reg_in_o.INTR_STATE.STRETCH_TIMEOUT.next          = event_stretch_timeout || stretch_timeout_intr_test;
  assign reg_in_o.INTR_STATE.SDA_UNSTABLE.next             = event_sda_unstable || sda_unstable_intr_test;
  assign reg_in_o.INTR_STATE.CMD_COMPLETE.next             = event_cmd_complete || cmd_complete_intr_test;
  assign reg_in_o.INTR_STATE.TX_STRETCH.next               = tx_stretch_intr_req;
  assign reg_in_o.INTR_STATE.TX_THRESHOLD.next             = tx_threshold_intr_req;
  assign reg_in_o.INTR_STATE.ACQ_STRETCH.next              = acq_stretch_intr_req;
  assign reg_in_o.INTR_STATE.UNEXP_STOP.next               = event_unexp_stop || unexp_stop_intr_test;
  assign reg_in_o.INTR_STATE.HOST_TIMEOUT.next             = event_host_timeout || host_timeout_intr_test;
  assign reg_in_o.INTR_STATE.SMBALERT.next                 = ~smbalert_n || smbalert_intr_test;
  assign reg_in_o.INTR_STATE.CONTROLLER_TX_FIFO_ERROR.next = controller_tx_fifo_error || controller_tx_fifo_error_intr_test;
  assign reg_in_o.INTR_STATE.CONTROLLER_RX_FIFO_ERROR.next = controller_rx_fifo_error || controller_rx_fifo_error_intr_test;
  assign reg_in_o.INTR_STATE.TARGET_TX_FIFO_ERROR.next     = target_tx_fifo_error || target_tx_fifo_error_intr_test;
  assign reg_in_o.INTR_STATE.TARGET_RX_FIFO_ERROR.next     = target_rx_fifo_error || target_rx_fifo_error_intr_test;


  // INTR_TEST Register
  assign fmt_threshold_intr_test            = reg_out_i.INTR_TEST.FMT_THRESHOLD.value;
  assign rx_threshold_intr_test             = reg_out_i.INTR_TEST.RX_THRESHOLD.value;
  assign acq_threshold_intr_test            = reg_out_i.INTR_TEST.ACQ_THRESHOLD.value;
  assign rx_overflow_intr_test              = reg_out_i.INTR_TEST.RX_OVERFLOW.value;
  assign controller_halt_intr_test          = reg_out_i.INTR_TEST.CONTROLLER_HALT.value;
  assign scl_interference_intr_test         = reg_out_i.INTR_TEST.SCL_INTERFERENCE.value;
  assign sda_interference_intr_test         = reg_out_i.INTR_TEST.SDA_INTERFERENCE.value;
  assign stretch_timeout_intr_test          = reg_out_i.INTR_TEST.STRETCH_TIMEOUT.value;
  assign sda_unstable_intr_test             = reg_out_i.INTR_TEST.SDA_UNSTABLE.value;
  assign cmd_complete_intr_test             = reg_out_i.INTR_TEST.CMD_COMPLETE.value;
  assign tx_stretch_intr_test               = reg_out_i.INTR_TEST.TX_STRETCH.value;
  assign tx_threshold_intr_test             = reg_out_i.INTR_TEST.TX_THRESHOLD.value;
  assign acq_stretch_intr_test              = reg_out_i.INTR_TEST.ACQ_STRETCH.value;
  assign unexp_stop_intr_test               = reg_out_i.INTR_TEST.UNEXP_STOP.value;
  assign host_timeout_intr_test             = reg_out_i.INTR_TEST.HOST_TIMEOUT.value;
  assign smbalert_intr_test                 = reg_out_i.INTR_TEST.SMBALERT.value;
  assign controller_tx_fifo_error_intr_test = reg_out_i.INTR_TEST.CONTROLLER_TX_FIFO_ERROR.value;
  assign controller_rx_fifo_error_intr_test = reg_out_i.INTR_TEST.CONTROLLER_RX_FIFO_ERROR.value;
  assign target_tx_fifo_error_intr_test     = reg_out_i.INTR_TEST.TARGET_TX_FIFO_ERROR.value;
  assign target_rx_fifo_error_intr_test     = reg_out_i.INTR_TEST.TARGET_RX_FIFO_ERROR.value;

  // SMBUS_CTRL Register
  assign reg_in_o.SMBUS_CTRL.SMBALERT.hwclr = event_target_addr_match;

  // CONTROLLER_EVENTS Register
  assign reg_in_o.CONTROLLER_EVENTS.NACK.next                   = event_nak;
  assign reg_in_o.CONTROLLER_EVENTS.UNHANDLED_NACK_TIMEOUT.next = event_unhandled_nak_timeout;
  assign reg_in_o.CONTROLLER_EVENTS.BUS_TIMEOUT.next            = event_bus_active_timeout &&
                                                                    !host_idle;
  assign reg_in_o.CONTROLLER_EVENTS.ARBITRATION_LOST.next       =
        event_controller_arbitration_lost;

  assign status_controller_halt = reg_out_i.CONTROLLER_EVENTS.intr; // OR of all register bits

  // TARGET_EVENTS Register
  assign reg_in_o.TARGET_EVENTS.TX_PENDING.next       = event_read_cmd_received &&
                                                          reg_out_i.CTRL.TX_STRETCH_CTRL_EN.value;
  assign reg_in_o.TARGET_EVENTS.BUS_TIMEOUT.next      = event_tx_bus_timeout;
  assign reg_in_o.TARGET_EVENTS.ARBITRATION_LOST.next = event_tx_arbitration_lost;

  // TARGET_EVENTS Start/Stop flags (W1C, no direct interrupt source)
  // These are implemented as sticky bits in the register block, so we only need
  // to pulse .next high when a start/stop event occurs.
  assign reg_in_o.TARGET_EVENTS.START_DETECT.next = start_event_for_target;
  assign reg_in_o.TARGET_EVENTS.STOP_DETECT.next  = stop_event_for_target;

  assign unhandled_tx_stretch_event = reg_out_i.TARGET_EVENTS.intr;


  /////////////////
  // SMBus Logic //
  /////////////////

  // SMBSUS# Signal
  prim_flop_2sync #(
    .Width             (1),
    .ResetValue        (1'b1),
    .EnablePrimCdcRand (1'b1)
  ) u_flop_2sync_smbsus (
    .clk_i,
    .rst_ni,
    .d_i               (smbsus_ni),
    .q_o               (smbsus_n)
  );

  assign reg_in_o.SMBUS_STATUS.SMBSUS.next = ~smbsus_n;
  assign smbsus_no = host_enable && !line_loopback ? ~reg_out_i.SMBUS_CTRL.SMBSUS.value : 1'b1;

  // SMBALERT# Signal
  prim_flop_2sync #(
    .Width             (1),
    .ResetValue        (1'b1),
    .EnablePrimCdcRand (1'b1)
  ) u_flop_2sync_smbalert (
    .clk_i,
    .rst_ni,
    .d_i               (smbalert_ni | ~smbus_en_i),
    .q_o               (smbalert_n)
  );

  assign reg_in_o.SMBUS_STATUS.SMBALERT.next = ~smbalert_n;
  assign smbalert_no = target_enable && !target_loopback ? ~reg_out_i.SMBUS_CTRL.SMBALERT.value :
                                                             1'b1;


  ///////////
  // Debug //
  ///////////

  // OR the error events into one debug bus bit, high only in the cycle of each event.
  logic any_error_event;

  assign any_error_event = event_nak
                           | event_controller_arbitration_lost
                           | event_scl_interference
                           | event_sda_interference
                           | event_stretch_timeout
                           | event_bus_active_timeout
                           | event_sda_unstable
                           | event_unhandled_nak_timeout;

  // Use the periph-clock-sampled SCL/SDA from the rx oversampling shift register
  // instead of the raw pad inputs so debug_o is fully sourced from clk_i. This
  // removes the ck_feedthru -> SMCCLK convergence on the SMC debug bus.
  assign debug_o = {any_error_event, target_idle, scl_rx_val[0], sda_rx_val[0]};


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(ControllerTxFifoDepthValid_A,
                       CONTROLLER_TX_FIFO_DEPTH > 0 && CONTROLLER_TX_FIFO_DEPTH_W <= MaxFifoDepthW)
  `OCAH_OT_ASSERT_INIT(ControllerRxFifoDepthValid_A,
                       CONTROLLER_RX_FIFO_DEPTH > 0 && CONTROLLER_RX_FIFO_DEPTH_W <= MaxFifoDepthW)
  `OCAH_OT_ASSERT_INIT(TargetTxFifoDepthValid_A,
                       TARGET_TX_FIFO_DEPTH > 0 && TARGET_TX_FIFO_DEPTH_W <= MaxFifoDepthW)
  `OCAH_OT_ASSERT_INIT(TargetRxFifoDepthValid_A,
                       TARGET_RX_FIFO_DEPTH > 0 && TARGET_RX_FIFO_DEPTH_W <= MaxFifoDepthW)
  `OCAH_OT_ASSERT_INIT(HostTimeoutWidthValid_A, $bits(host_timeout) == $bits
                       (reg_out_i.HOST_TIMEOUT_CTRL.VAL.value))

  `OCAH_OT_ASSERT(HostTimeoutValuePreserved_A,
                  host_timeout == reg_out_i.HOST_TIMEOUT_CTRL.VAL.value)

endmodule
