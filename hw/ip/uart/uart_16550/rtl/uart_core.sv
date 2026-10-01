// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Bind 16550 TX/RX datapaths, FIFOs, modem status, and interrupts to the register structs.
//
// TX_FIFO_DEPTH and RX_FIFO_DEPTH size the FIFOs; localparams derive baud, FIFO
// depth/threshold, timeout, and trigger-level types.
// reg_out_i/reg_in_o are the generated register HW outputs and inputs.
// Exposes serial, modem, DMA ready, err_o, and irq_o.
// A zero divisor latch (DLM:DLL) disables both the transmitter and the receiver.

module uart_core
  import uart_16550_pkg::*;
#(
  parameter int unsigned TX_FIFO_DEPTH = 16,  // Transmit FIFO depth. In uart_16550, a power of 2
                                              // from 4 to 4096.
  parameter int unsigned RX_FIFO_DEPTH = 16,  // Receive FIFO depth. In uart_16550, a power of 2
                                              // from 4 to 4096.

  localparam int unsigned BAUD_CNT_WIDTH = 16,  // Baud-rate divider counter width.
  localparam type         baud_cnt_t = logic [BAUD_CNT_WIDTH-1:0],  // Baud divider counter type.

  localparam int unsigned RX_FIFO_DEPTH_WIDTH = $clog2(RX_FIFO_DEPTH + 1),  // Bits to hold an RX FIFO fill level of 0 to RX_FIFO_DEPTH.
  localparam type         rx_fifo_depth_t = logic [RX_FIFO_DEPTH_WIDTH-1:0],  // RX FIFO fill-level type.

  localparam int unsigned RX_FIFO_THRESHOLD_WIDTH = $clog2(4096 + 1),  // Bits to hold the largest RX trigger level, 4096 entries.
  localparam type         rx_fifo_threshold_t = logic [RX_FIFO_THRESHOLD_WIDTH-1:0],  // RX FIFO threshold type.

  localparam int unsigned TIMEOUT_CNT_WIDTH = $clog2(MAX_FRAME_LEN * TIMEOUT_CHAR_CNT),  // Bits to count baud ticks over four maximum-length frames.
  localparam type         timeout_cnt_t = logic [TIMEOUT_CNT_WIDTH-1:0],  // Character-timeout counter type.

  localparam int unsigned TRIGGER_LEVEL_WIDTH = $clog2(NUM_TRIGGER_LEVELS),  // Bits to encode one of the RX trigger levels.
  localparam type         trigger_level_t = logic [TRIGGER_LEVEL_WIDTH-1:0]  // RX trigger-level select type.
) (
  input  logic                clk_i,    // System clock.
  input  logic                rst_ni,   // Active-low reset.

  input  uart_16550_reg_out_t reg_out_i,  // Software-programmed register fields from the generated
                                          // register block.
  output uart_16550_reg_in_t  reg_in_o,  // Hardware-driven inputs to the generated register block.

  input  logic                rx_i,     // Asynchronous; two-flop synchronized and 3-sample majority
                                        // filtered. Ignored in system or line loopback.
  output logic                tx_o,     // Registered; low during a set break. Held high in system
                                        // loopback and equal to rx_i in line loopback.

  input  logic                cts_ni,   // Clear To Send, active-low; synchronized into MSR. Drives
                                        // rts_no in line loopback.
  input  logic                dsr_ni,   // Data Set Ready, active-low; synchronized into MSR. Drives
                                        // dtr_no in line loopback.
  input  logic                ri_ni,    // Ring Indicator, active-low; synchronized into MSR. Drives
                                        // out1_no in line loopback.
  input  logic                dcd_ni,   // Data Carrier Detect, active-low; synchronized into MSR.
                                        // Drives out2_no in line loopback.

  output logic                rts_no,   // Request To Send, active-low; the inverted MCR RTS bit,
                                        // high in system loopback.
  output logic                dtr_no,   // Data Terminal Ready, active-low; the inverted MCR DTR
                                        // bit, high in system loopback.
  output logic                out1_no,  // Inverted MCR OUT1 bit, active-low; high in system
                                        // loopback.
  output logic                out2_no,  // Inverted MCR OUT2 bit, active-low; high in system
                                        // loopback.

  output logic                rxrdy_o,  // Active-high DMA receive request: in mode 0 while the RX
                                        // FIFO is not empty; in mode 1 from the trigger level or a
                                        // character timeout until the FIFO empties.
  output logic                txrdy_o,  // Active-high DMA transmit request: in mode 0 while the TX
                                        // FIFO is empty; in mode 1 until it fills, then again once
                                        // it drains.

  output logic                err_o,    // High on a data-parity or pointer integrity error in the
                                        // TX or RX FIFO, or a parity error in the holding register
                                        // used in non-FIFO mode.

  output logic                irq_o     // Interrupt request, active-high; the OR of the enabled
                                        // interrupt sources.
);

  //////////////////////////////////
  // Type and Signal Declarations //
  //////////////////////////////////

  typedef struct packed {
    logic       break_err;
    logic       framing_err;
    logic       parity_err;
    logic [7:0] character;
  } rx_fifo_rbr_entry_t;

  logic [7:0] uart_rdata;
  logic tick_baud_x16, rx_tick_baud;
  rx_fifo_depth_t  rx_fifo_depth;
  rx_fifo_depth_t  rx_fifo_depth_prev_q;
  timeout_cnt_t rx_timeout_count_d, rx_timeout_count_q, uart_rxto_val;
  logic rx_fifo_depth_changed, uart_rxto_en;
  logic tx_enable, rx_enable;
  logic sys_loopback, line_loopback;
  logic uart_fifo_en;
  logic uart_fifo_rxrst, uart_fifo_txrst;
  logic rbr_rst, thr_rst;
  trigger_level_t uart_fifo_rxilvl;
  logic [7:0] tx_fifo_thr_wdata, tx_fifo_thr_rdata;
  logic tx_fifo_thr_wvalid;
  logic tx_fifo_thr_rready, tx_fifo_thr_rvalid;
  logic tx_fifo_thr_wready, tx_uart_idle;
  logic            uart_tx_out;
  logic            tx_out;
  logic            tx_out_q;
  logic [7:0]      rx_fifo_rbr_wdata;
  logic rx_valid, rx_fifo_rbr_wvalid, rx_fifo_rbr_rvalid;
  logic rx_fifo_rbr_wready, rx_uart_idle;
  logic            rx_fifo_rbr_rready;
  logic            rx_sync;
  logic            rx_in;
  logic frame_err, break_err, parity_err, rx_char_err;
  logic            allzero_err;
  logic            event_rx_overflow;
  logic event_rx_frame_err, event_rx_timeout, event_rx_parity_err;
  logic            rx_watermark_d;
  logic            rx_fifo_threshold_supported;
  rx_fifo_threshold_t rx_fifo_threshold;
  logic            tx_uart_idle_q;
  logic fifo_thr_rbr_err, rx_fifo_rbr_err, tx_fifo_thr_err;
  logic fifo_error_intr_test, fifo_error_intr_en;
  logic reception_timeout_intr_test;
  logic received_data_ready_intr_test, received_data_ready_intr_en;
  logic transmitter_holding_register_empty_intr_test, transmitter_holding_register_empty_intr_en;
  logic receiver_line_status_intr_test, receiver_line_status_intr_en;
  logic modem_status_intr_test, modem_status_intr_en;
  interrupt_reqs_t intr_reqs; // Interrupt requests going into the priority encoder
  interrupt_id_e   intr_id;
  logic            iir_read;
  dma_mode_e       dma_mode;
  baud_cnt_t       baud_rate_divisor;
  logic [3:0]      word_length;
  logic set_break, stick_parity, even_parity, parity_enable, extra_stop_bit;


  /////////////////////////
  // Baud Rate Generator //
  /////////////////////////

  baud_cnt_t baud_count;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      baud_count <= baud_cnt_t'(0);
    end else if (!tx_enable && !rx_enable) begin
      baud_count <= baud_cnt_t'(0);
    end else if (baud_count == baud_cnt_t'(0)) begin
      baud_count <= baud_rate_divisor;
    end else begin
      baud_count <= baud_count - baud_cnt_t'(1);
    end
  end

  assign tick_baud_x16 = (tx_enable || rx_enable) && baud_count == baud_cnt_t'(0);


  //////////////
  // TX Logic //
  //////////////

  assign tx_fifo_thr_rready = tx_enable && tx_uart_idle && tx_fifo_thr_rvalid;

  // TX FIFO/THR Muxing
  logic tx_fifo_wvalid, thr_wvalid;
  logic [7:0] tx_fifo_wdata, thr_wdata;
  logic tx_fifo_rready, thr_rready;

  logic tx_fifo_wready, thr_wready;
  logic tx_fifo_rvalid, thr_rvalid;
  logic [7:0] tx_fifo_rdata, thr_rdata;
  logic tx_fifo_err, thr_err;

  always_comb begin
    if (uart_fifo_en) begin
      // TX FIFO requests
      tx_fifo_wvalid = tx_fifo_thr_wvalid;
      tx_fifo_wdata  = tx_fifo_thr_wdata;
      tx_fifo_rready = tx_fifo_thr_rready;
      // TX FIFO/THR responses
      tx_fifo_thr_wready = tx_fifo_wready;
      tx_fifo_thr_rvalid = tx_fifo_rvalid;
      tx_fifo_thr_rdata  = tx_fifo_rdata;
      tx_fifo_thr_err    = tx_fifo_err;
      // THR requests
      thr_wvalid = 1'b0;
      thr_wdata  = 8'h0;
      thr_rready = 1'b0;
    end else begin
      // TX FIFO requests
      tx_fifo_wvalid = 1'b0;
      tx_fifo_wdata  = 8'h0;
      tx_fifo_rready = 1'b0;
      // TX FIFO/THR responses
      tx_fifo_thr_wready = thr_wready;
      tx_fifo_thr_rvalid = thr_rvalid;
      tx_fifo_thr_rdata  = thr_rdata;
      tx_fifo_thr_err    = thr_err;
      // THR requests
      thr_wvalid = tx_fifo_thr_wvalid;
      thr_wdata  = tx_fifo_thr_wdata;
      thr_rready = tx_fifo_thr_rready;
    end
  end

  prim_fifo_sync_parity #(
    .WIDTH                (8),
    .PASS                 (1'b0),
    .DEPTH                (TX_FIFO_DEPTH),
    .OUTPUT_ZERO_IF_EMPTY (1'b1),
    .NEVER_CLEARS         (1'b0),
    .SECURE               (1'b1)  // Pointer and data error checking
  ) u_uart_txfifo (
    .clk_i,
    .rst_ni,
    .clr_i             (uart_fifo_txrst),
    .wvalid_i          (tx_fifo_wvalid),
    .wready_o          (tx_fifo_wready),
    .wdata_i           (tx_fifo_wdata),
    .rvalid_o          (tx_fifo_rvalid),
    .rready_i          (tx_fifo_rready),
    .rdata_o           (tx_fifo_rdata),
    .full_o            (/* UNUSED */),
    .depth_o           (/* UNUSED */),
    .err_o             (tx_fifo_err)
  );

  // Transmitter Holding Register (THR)
  logic thr_parity;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      thr_rvalid <= 1'b0;
      thr_rdata  <= 8'h0;
      thr_parity <= 1'h0;
    end else if (thr_rst) begin  // Clear
      thr_rvalid <= 1'b0;
      thr_rdata  <= 8'h0;
      thr_parity <= 1'h0;
    end else if (thr_rready && thr_rvalid) begin  // Read
      thr_rvalid <= 1'b0;
      thr_rdata  <= 8'h0;
      thr_parity <= 1'h0;
    end else if (thr_wready && thr_wvalid) begin  // Write
      thr_rvalid <= 1'b1;
      thr_rdata  <= thr_wdata;
      thr_parity <= ~^thr_wdata;
    end
  end

  assign thr_wready = !thr_rvalid;
  assign thr_err    = thr_rvalid && ~^{thr_parity, thr_rdata};

  // TX logic
  logic [7:0] tx_data;

  always_comb begin
    for (int i = 0; i < 8; i++) begin
      if (i < word_length) begin
        tx_data[i] = tx_fifo_thr_rdata[i];
      end else begin
        tx_data[i] = 1'b0;
      end
    end
  end

  uart_tx u_uart_tx (
    .clk_i,
    .rst_ni,
    .tx_enable_i      (tx_enable),
    .tick_baud_x16_i  (tick_baud_x16),
    .parity_enable_i  (parity_enable),
    .word_length_i    (word_length),
    .extra_stop_bit_i (extra_stop_bit),
    .wr_i             (tx_fifo_thr_rready),
    .wr_parity_i      (stick_parity ? ~even_parity : ~^tx_data ^ even_parity),
    .wr_data_i        (tx_data),
    .idle_o           (tx_uart_idle),
    .tx_o             (uart_tx_out)
  );

  assign tx_out = set_break ? 1'b0 : uart_tx_out;

  assign tx_o = line_loopback ? rx_i : tx_out_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      tx_out_q <= 1'b1;
    end else if (sys_loopback) begin
      tx_out_q <= 1'b1;
    end else begin
      tx_out_q <= tx_out;
    end
  end


  //////////////
  // RX Logic //
  //////////////

  // Sync the incoming data
  prim_flop_2sync #(
    .Width      (1),
    .ResetValue (1'b1)
  ) u_flop_2sync_rx (
    .clk_i,
    .rst_ni,
    .d_i        (rx_i),
    .q_o        (rx_sync)
  );

  // Based on: en.wikipedia.org/wiki/Repetition_code mentions the use of a majority filter
  // in UART to ignore brief noise spikes
  logic rx_sync_q, rx_sync_q2, rx_in_maj;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      rx_sync_q  <= 1'h1;
      rx_sync_q2 <= 1'h1;
    end else begin
      rx_sync_q  <= rx_sync;
      rx_sync_q2 <= rx_sync_q;
    end
  end

  assign rx_in_maj = count_ones({29'h0, rx_sync, rx_sync_q, rx_sync_q2}) >= 2'd2;
  assign rx_in = sys_loopback  ? tx_out :
                   line_loopback ? 1'h1   :
                   rx_in_maj;

  uart_rx u_uart_rx (
    .clk_i,
    .rst_ni,
    .rx_enable_i      (rx_enable),
    .tick_baud_x16_i  (tick_baud_x16),
    .parity_enable_i  (parity_enable),
    .parity_odd_i     (!even_parity),
    .parity_force_i   (stick_parity),
    .word_length_i    (word_length),
    .extra_stop_bit_i (extra_stop_bit),
    .tick_baud_o      (rx_tick_baud),
    .rx_valid_o       (rx_valid),
    .rx_data_o        (rx_fifo_rbr_wdata),
    .idle_o           (rx_uart_idle),
    .frame_err_o      (event_rx_frame_err),
    .rx_i             (rx_in),
    .rx_parity_err_o  (event_rx_parity_err)
  );

  assign rx_fifo_rbr_wvalid = rx_valid;

  assign allzero_err = event_rx_frame_err && rx_fifo_rbr_wdata == 8'h0;

  // RX FIFO/RBR Muxing
  logic rx_fifo_wvalid, rbr_wvalid;
  rx_fifo_rbr_entry_t rx_fifo_wdata, rbr_wdata;
  logic rx_fifo_rready, rbr_rready;

  logic rx_fifo_wready, rbr_wready;
  logic rx_fifo_rvalid, rbr_rvalid;
  rx_fifo_rbr_entry_t rx_fifo_rdata, rbr_rdata;
  logic rx_fifo_err, rbr_err;

  always_comb begin
    if (uart_fifo_en) begin
      // RX FIFO requests
      rx_fifo_wvalid            = rx_fifo_rbr_wvalid;
      rx_fifo_wdata.break_err   = allzero_err;
      rx_fifo_wdata.framing_err = event_rx_frame_err;
      rx_fifo_wdata.parity_err  = event_rx_parity_err;
      rx_fifo_wdata.character   = rx_fifo_rbr_wdata;
      rx_fifo_rready            = rx_fifo_rbr_rready;
      // RX FIFO/RBR responses
      rx_fifo_rbr_wready = rx_fifo_wready;
      rx_fifo_rbr_rvalid = rx_fifo_rvalid;
      uart_rdata         = rx_fifo_rdata.character;
      break_err          = rx_fifo_rdata.break_err;
      frame_err          = rx_fifo_rdata.framing_err;
      parity_err         = rx_fifo_rdata.parity_err;
      rx_char_err        = rx_fifo_rdata.break_err   ||
                                 rx_fifo_rdata.framing_err ||
                                 rx_fifo_rdata.parity_err;
      rx_fifo_rbr_err    = rx_fifo_err;
      // RBR requests
      rbr_wvalid = 1'b0;
      rbr_wdata  = rx_fifo_rbr_entry_t'(0);
      rbr_rready = 1'b0;
    end else begin
      // RX FIFO requests
      rx_fifo_wvalid = 1'b0;
      rx_fifo_wdata  = rx_fifo_rbr_entry_t'(0);
      rx_fifo_rready = 1'b0;
      // RX FIFO/RBR responses
      rx_fifo_rbr_wready = rbr_wready;
      rx_fifo_rbr_rvalid = rbr_rvalid;
      uart_rdata         = rbr_rdata.character;
      break_err          = rbr_rdata.break_err;
      frame_err          = rbr_rdata.framing_err;
      parity_err         = rbr_rdata.parity_err;
      rx_char_err        = rbr_rdata.break_err   ||
                                 rbr_rdata.framing_err ||
                                 rbr_rdata.parity_err;
      rx_fifo_rbr_err    = rbr_err;
      // RBR requests
      rbr_wvalid            = rx_fifo_rbr_wvalid;
      rbr_wdata.break_err   = allzero_err;
      rbr_wdata.framing_err = event_rx_frame_err;
      rbr_wdata.parity_err  = event_rx_parity_err;
      rbr_wdata.character   = rx_fifo_rbr_wdata;
      rbr_rready            = rx_fifo_rbr_rready;
    end
  end

  prim_fifo_sync_parity #(
    .WIDTH                ($bits(rx_fifo_rbr_entry_t)),
    .PASS                 (1'b0),
    .DEPTH                (RX_FIFO_DEPTH),
    .OUTPUT_ZERO_IF_EMPTY (1'b1),
    .NEVER_CLEARS         (1'b0),
    .SECURE               (1'b1)  // Error checking
  ) u_uart_rxfifo (
    .clk_i,
    .rst_ni,
    .clr_i             (uart_fifo_rxrst),
    .wvalid_i          (rx_fifo_wvalid),
    .wready_o          (rx_fifo_wready),
    .wdata_i           (rx_fifo_wdata),
    .rvalid_o          (rx_fifo_rvalid),
    .rready_i          (rx_fifo_rready),
    .rdata_o           (rx_fifo_rdata),
    .full_o            (/* UNUSED */),
    .depth_o           (rx_fifo_depth),
    .err_o             (rx_fifo_err)
  );

  // Receiver Buffer Register (RBR)
  logic rbr_parity;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      rbr_rvalid <= 1'b0;
      rbr_rdata  <= rx_fifo_rbr_entry_t'(0);
      rbr_parity <= 1'h0;
    end else if (rbr_rst) begin  // Clear
      rbr_rvalid <= 1'b0;
      rbr_rdata  <= rx_fifo_rbr_entry_t'(0);
      rbr_parity <= 1'h0;
    end else if (rbr_rready && rbr_rvalid) begin  // Read
      rbr_rvalid <= 1'b0;
      rbr_rdata  <= rx_fifo_rbr_entry_t'(0);
      rbr_parity <= 1'h0;
    end else if (rbr_wvalid) begin
      // Write. UART 16550: Overwrite existing character with new one.
      rbr_rvalid <= 1'b1;
      rbr_rdata  <= rbr_wdata;
      rbr_parity <= ~^rbr_wdata;
    end
  end

  assign rbr_wready = !rbr_rvalid;
  assign rbr_err = rbr_rvalid && ~^{rbr_parity, rbr_rdata};


  ///////////////
  // DMA Logic //
  ///////////////

  logic dma_mode_1_en;
  logic dma_mode_1_rxrdy, dma_mode_1_txrdy;

  assign dma_mode_1_en = uart_fifo_en && dma_mode == DMA_MODE_1;

  typedef enum logic {
    ST_DMA_MODE_1_RX_IDLE  = 1'd0,
    ST_DMA_MODE_1_RX_READY = 1'd1
  } dma_mode_1_rx_fsm_state_e;

  dma_mode_1_rx_fsm_state_e dma_mode_1_rx_fsm_state, dma_mode_1_rx_fsm_state_next;

  always_comb begin
    dma_mode_1_rxrdy = 1'b0;
    dma_mode_1_rx_fsm_state_next = dma_mode_1_rx_fsm_state;

    unique case (dma_mode_1_rx_fsm_state)
      ST_DMA_MODE_1_RX_IDLE: begin
        if (dma_mode_1_en) begin
          if (rx_watermark_d || event_rx_timeout) begin
            // RX FIFO trigger level reached or timeout
            dma_mode_1_rxrdy = 1'b1;
            dma_mode_1_rx_fsm_state_next = ST_DMA_MODE_1_RX_READY;
          end else begin
            dma_mode_1_rxrdy = 1'b0;
            dma_mode_1_rx_fsm_state_next = ST_DMA_MODE_1_RX_IDLE;
          end
        end else begin
          dma_mode_1_rxrdy = 1'b0;
          dma_mode_1_rx_fsm_state_next = ST_DMA_MODE_1_RX_IDLE;
        end
      end
      ST_DMA_MODE_1_RX_READY: begin
        if (!rx_fifo_rvalid) begin  // RX FIFO empty
          dma_mode_1_rxrdy = 1'b0;
          dma_mode_1_rx_fsm_state_next = ST_DMA_MODE_1_RX_IDLE;
        end else begin
          dma_mode_1_rxrdy = 1'b1;
          dma_mode_1_rx_fsm_state_next = ST_DMA_MODE_1_RX_READY;
        end
      end
      default: begin
        dma_mode_1_rxrdy = 1'b0;
        dma_mode_1_rx_fsm_state_next = ST_DMA_MODE_1_RX_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      dma_mode_1_rx_fsm_state <= ST_DMA_MODE_1_RX_IDLE;
    end else begin
      dma_mode_1_rx_fsm_state <= dma_mode_1_rx_fsm_state_next;
    end
  end

  typedef enum logic {
    ST_DMA_MODE_1_TX_IDLE      = 1'd0,
    ST_DMA_MODE_1_TX_NOT_READY = 1'd1
  } dma_mode_1_tx_fsm_state_e;

  dma_mode_1_tx_fsm_state_e dma_mode_1_tx_fsm_state, dma_mode_1_tx_fsm_state_next;

  always_comb begin
    dma_mode_1_txrdy = 1'b0;
    dma_mode_1_tx_fsm_state_next = dma_mode_1_tx_fsm_state;

    unique case (dma_mode_1_tx_fsm_state)
      ST_DMA_MODE_1_TX_IDLE: begin
        if (dma_mode_1_en) begin
          if (!tx_fifo_wready) begin  // TX FIFO full
            dma_mode_1_txrdy = 1'b0;
            dma_mode_1_tx_fsm_state_next = ST_DMA_MODE_1_TX_NOT_READY;
          end else begin
            dma_mode_1_txrdy = 1'b1;
            dma_mode_1_tx_fsm_state_next = ST_DMA_MODE_1_TX_IDLE;
          end
        end else begin
          dma_mode_1_txrdy = 1'b0;
          dma_mode_1_tx_fsm_state_next = ST_DMA_MODE_1_TX_IDLE;
        end
      end
      ST_DMA_MODE_1_TX_NOT_READY: begin
        if (!tx_fifo_rvalid) begin  // TX FIFO empty
          dma_mode_1_txrdy = 1'b1;
          dma_mode_1_tx_fsm_state_next = ST_DMA_MODE_1_TX_IDLE;
        end else begin
          dma_mode_1_txrdy = 1'b0;
          dma_mode_1_tx_fsm_state_next = ST_DMA_MODE_1_TX_NOT_READY;
        end
      end
      default: begin
        dma_mode_1_txrdy = 1'b0;
        dma_mode_1_tx_fsm_state_next = ST_DMA_MODE_1_TX_IDLE;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      dma_mode_1_tx_fsm_state <= ST_DMA_MODE_1_TX_IDLE;
    end else begin
      dma_mode_1_tx_fsm_state <= dma_mode_1_tx_fsm_state_next;
    end
  end

  always_comb begin
    if (dma_mode_1_en) begin  // DMA mode 1
      rxrdy_o = dma_mode_1_rxrdy;
      txrdy_o = dma_mode_1_txrdy;
    end else begin  // DMA mode 0
      rxrdy_o =  rx_fifo_rbr_rvalid;
      txrdy_o = !tx_fifo_thr_rvalid;
    end
  end


  /////////////////
  // Error Logic //
  /////////////////

  assign fifo_thr_rbr_err = tx_fifo_thr_err || rx_fifo_rbr_err;
  assign err_o = fifo_thr_rbr_err;


  /////////////////////
  // Interrupt Logic //
  /////////////////////

  assign irq_o = |intr_reqs;

  // Reception Timeout Interrupt
  // As per UART 16550, the Reception Timeout Interrupt is only for FIFO mode
  assign uart_rxto_en = uart_fifo_en;
  // UART 16550: timeout is 4 characters
  assign uart_rxto_val = timeout_cnt_t'(4 * (1 + word_length + parity_enable +
                                               (extra_stop_bit + 1)));

  assign rx_fifo_depth_changed = rx_fifo_depth != rx_fifo_depth_prev_q;

  assign rx_timeout_count_d =
            // Don't count if timeout feature not enabled.
            // Will never reach timeout val + lower power.
            !uart_rxto_en                        ? timeout_cnt_t'(0) :
            // Reset count if Reception Timeout Interrupt is set
            event_rx_timeout                     ? timeout_cnt_t'(0) :
            // Reset count upon change in fifo level: covers both read and receiving a new byte
            rx_fifo_depth_changed                ? timeout_cnt_t'(0) :
            // Reset count if no bytes are pending
            rx_fifo_depth == rx_fifo_depth_t'(0) ? timeout_cnt_t'(0) :
            // Increment if at rx baud tick
            rx_tick_baud                         ? rx_timeout_count_q + timeout_cnt_t'(1) :
            rx_timeout_count_q;

  assign event_rx_timeout = uart_rxto_en && rx_timeout_count_q == uart_rxto_val;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      rx_timeout_count_q   <= 24'd0;
      rx_fifo_depth_prev_q <= rx_fifo_depth_t'(0);
    end else begin
      rx_timeout_count_q   <= rx_timeout_count_d;
      rx_fifo_depth_prev_q <= rx_fifo_depth;
    end
  end

  assign event_rx_overflow = rx_fifo_wvalid && !rx_fifo_wready;

  logic reception_timeout_intr;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      reception_timeout_intr <= 1'b0;
    end else if (event_rx_timeout) begin
      reception_timeout_intr <= 1'b1;
    end else if (rx_fifo_rready) begin
      reception_timeout_intr <= 1'b0;
    end
  end

  assign intr_reqs.reception_timeout = reception_timeout_intr || reception_timeout_intr_test;

  // Received Data Ready Interrupt
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      tx_uart_idle_q <= 1'b1;
    end else begin
      tx_uart_idle_q <= tx_uart_idle;
    end
  end

  always_comb begin
    rx_fifo_threshold = '0;
    rx_fifo_threshold_supported = 1'b1;
    unique case (uart_fifo_rxilvl)
      4'h0:    rx_fifo_threshold = rx_fifo_threshold_t'(1);  // UART 16550
      4'h1:    rx_fifo_threshold = rx_fifo_threshold_t'(4);  // UART 16550
      4'h2:    rx_fifo_threshold = rx_fifo_threshold_t'(8);  // UART 16550
      4'h3:    rx_fifo_threshold = rx_fifo_threshold_t'(14); // UART 16550
      4'h4:    rx_fifo_threshold = rx_fifo_threshold_t'(32);
      4'h5:    rx_fifo_threshold = rx_fifo_threshold_t'(64);
      4'h6:    rx_fifo_threshold = rx_fifo_threshold_t'(128);
      4'h7:    rx_fifo_threshold = rx_fifo_threshold_t'(256);
      4'h8:    rx_fifo_threshold = rx_fifo_threshold_t'(512);
      4'h9:    rx_fifo_threshold = rx_fifo_threshold_t'(1024);
      4'ha:    rx_fifo_threshold = rx_fifo_threshold_t'(2048);
      4'hb:    rx_fifo_threshold = rx_fifo_threshold_t'(4096);
      default: rx_fifo_threshold_supported = 1'b0;
    endcase

    rx_fifo_threshold_supported &= RX_FIFO_DEPTH >= rx_fifo_threshold;
    rx_watermark_d = uart_fifo_en && rx_fifo_threshold_supported &&
                     rx_fifo_threshold_t'(rx_fifo_depth) >= rx_fifo_threshold;
  end

  assign intr_reqs.received_data_ready =
        ((uart_fifo_en ? rx_watermark_d : rbr_rvalid) || received_data_ready_intr_test) &&
        received_data_ready_intr_en;

  // Transmitter Holding Register Empty Interrupt
  logic tx_fifo_thr_empty, tx_fifo_thr_empty_q;

  assign tx_fifo_thr_empty = !tx_fifo_thr_rvalid;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      tx_fifo_thr_empty_q <= 1'b1;
    end else begin
      tx_fifo_thr_empty_q <= tx_fifo_thr_empty;
    end
  end

  logic transmitter_holding_register_empty_intr_cleared;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      transmitter_holding_register_empty_intr_cleared <= 1'b0;
    end else if (tx_fifo_thr_empty && !tx_fifo_thr_empty_q) begin
      transmitter_holding_register_empty_intr_cleared <= 1'b0;
    end else if (tx_fifo_thr_wvalid ||
                    intr_id == TRANSMITTER_HOLDING_REGISTER_EMPTY &&
                    iir_read) begin
      transmitter_holding_register_empty_intr_cleared <= 1'b1;
    end
  end

  assign intr_reqs.transmitter_holding_register_empty =
        (tx_fifo_thr_empty && !transmitter_holding_register_empty_intr_cleared ||
         transmitter_holding_register_empty_intr_test) &&
         transmitter_holding_register_empty_intr_en;

  // FIFO Error Interrupt
  assign intr_reqs.fifo_error = (fifo_thr_rbr_err || fifo_error_intr_test) && fifo_error_intr_en;


  ///////////////
  // CSR Logic //
  ///////////////

  logic [1:0] rx_trigger_level_ms2b;  // RX FIFO trigger level configuration
  logic rts, dtr, out1, out2;  // Modem control bits

  // Read Buffer Register (RBR)
  assign reg_in_o.main.RBR.rd_ack                 =  reg_out_i.main.RBR.req &&
                                                      !reg_out_i.main.RBR.req_is_wr;
  assign rx_fifo_rbr_rready                       =  reg_out_i.main.RBR.req &&
                                                      !reg_out_i.main.RBR.req_is_wr;
  assign reg_in_o.main.RBR.rd_data._reserved_31_8 =  24'h0;
  assign reg_in_o.main.RBR.rd_data.DATA           =  uart_rdata;

  // Transmitter Holding Register (THR)
  assign reg_in_o.main_wo.THR.wr_ack =  reg_out_i.main_wo.THR.req &&
                                          reg_out_i.main_wo.THR.req_is_wr;
  assign tx_fifo_thr_wvalid          =  reg_out_i.main_wo.THR.req &&
                                          reg_out_i.main_wo.THR.req_is_wr &&
                                         |reg_out_i.main_wo.THR.wr_biten[7:0];
  assign tx_fifo_thr_wdata           =  reg_out_i.main_wo.THR.wr_data[7:0] &
                                          reg_out_i.main_wo.THR.wr_biten[7:0];

  // Interrupt Enable Register (IER)
  assign received_data_ready_intr_en                = reg_out_i.main.IER.ERBFI.value;
  assign transmitter_holding_register_empty_intr_en = reg_out_i.main.IER.ETBEI.value;
  assign receiver_line_status_intr_en               = reg_out_i.main.IER.ELSI.value;
  assign modem_status_intr_en                       = reg_out_i.main.IER.EDSSI.value;
  assign fifo_error_intr_en                         = reg_out_i.main.IER.EFEI.value;

  // Interrupt Identification Register (IIR)
  always_comb begin
    casez (intr_reqs)
      6'b1?????: intr_id = FIFO_ERROR;                         // Highest priority
      6'b01????: intr_id = RECEIVER_LINE_STATUS;
      6'b001???: intr_id = RECEPTION_TIMEOUT;
      6'b0001??: intr_id = RECEIVED_DATA_READY;
      6'b00001?: intr_id = TRANSMITTER_HOLDING_REGISTER_EMPTY;
      6'b000001: intr_id = MODEM_STATUS;                       // Lowest priority
      default:   intr_id = interrupt_id_e'(0);
    endcase
  end

  assign reg_in_o.main.IIR.INTERRUPT_PENDING.next = ~irq_o; // Active-low
  assign reg_in_o.main.IIR.INTERRUPT_ID.next      = intr_id;
  assign reg_in_o.main.IIR.FIFOS_ENABLED.next     = {2{uart_fifo_en}}; // 2'h3 - FIFOs enabled

  assign iir_read = reg_out_i.main.IIR.INTERRUPT_PENDING.rd_swacc;

  // FIFO Control Register (FCR)
  logic uart_fifo_en_q, fifo_en_changed;

  // FIFO enable and enable changed
  assign uart_fifo_en = reg_out_i.main_wo.FCR.FIFO_ENABLE.value;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      uart_fifo_en_q <= 1'b0;
    end else begin
      uart_fifo_en_q <= uart_fifo_en;
    end
  end

  assign fifo_en_changed = uart_fifo_en != uart_fifo_en_q;

  // FIFOs' resets
  assign uart_fifo_rxrst = reg_out_i.main_wo.FCR.RCVR_FIFO_RESET.value || fifo_en_changed;
  assign uart_fifo_txrst = reg_out_i.main_wo.FCR.XMIT_FIFO_RESET.value || fifo_en_changed;
  assign rbr_rst = fifo_en_changed;
  assign thr_rst = fifo_en_changed;

  // DMA mode
  assign dma_mode = dma_mode_e'(reg_out_i.main_wo.FCR.DMA_MODE_SELECT.value);

  // RX trigger level
  logic [1:0] rx_trigger_level_ls2b;

  assign rx_trigger_level_ls2b = reg_out_i.main_wo.FCR.RCVR_TRIGGER.value;
  assign uart_fifo_rxilvl = {rx_trigger_level_ms2b, rx_trigger_level_ls2b};

  // Modem Control Register (MCR)
  // Modem interface control bits
  assign rts  = reg_out_i.main.MCR.RTS.value;
  assign dtr  = reg_out_i.main.MCR.DTR.value;
  assign out1 = reg_out_i.main.MCR.OUT1.value;
  assign out2 = reg_out_i.main.MCR.OUT2.value;

  // Loopback control
  assign sys_loopback  = reg_out_i.main.MCR.LOOP.value;
  assign line_loopback = reg_out_i.main.MCR.LINE_LOOPBACK.value;

  always_comb begin
    if (line_loopback) begin
      // In line loopback mode, the modem control outputs are controlled by the modem status
      // inputs
      rts_no  = cts_ni;
      dtr_no  = dsr_ni;
      out1_no = ri_ni;
      out2_no = dcd_ni;
    end else if (sys_loopback) begin
      // In system loopback mode (if line loopback is disabled), the modem status outputs are
      // deasserted
      rts_no  = 1'b1;
      dtr_no  = 1'b1;
      out1_no = 1'b1;
      out2_no = 1'b1;
    end else begin  // In normal mode, the modem status outputs are controlled by the MCR
      rts_no  = ~rts;
      dtr_no  = ~dtr;
      out1_no = ~out1;
      out2_no = ~out2;
    end
  end

  // Line Control Register (LCR)
  // Frame format configuration
  assign word_length    = get_word_length(reg_out_i.main.LCR.WLS.value);
  assign extra_stop_bit =                 reg_out_i.main.LCR.STB.value;
  assign parity_enable  =                 reg_out_i.main.LCR.PEN.value;
  assign even_parity    =                 reg_out_i.main.LCR.EPS.value;

  // TX override
  assign stick_parity = reg_out_i.main.LCR.STICK_PARITY.value;
  assign set_break    = reg_out_i.main.LCR.SET_BREAK.value;

  // Line Status Register (LSR)
  // RX data ready
  assign reg_in_o.main.LSR.DR.next = rx_fifo_rbr_rvalid;

  // RX errors
  assign reg_in_o.main.LSR.OE.next = event_rx_overflow;
  assign reg_in_o.main.LSR.PE.next = parity_err;
  assign reg_in_o.main.LSR.FE.next = frame_err;
  assign reg_in_o.main.LSR.BI.next = break_err;
  assign reg_in_o.main.LSR.ERROR_IN_RCVR_FIFO.next = rx_char_err; // OR of the 3 bits above
  assign intr_reqs.receiver_line_status =
        (reg_out_i.main.LSR.intr || receiver_line_status_intr_test) &&
        receiver_line_status_intr_en;

  // TX empty status
  assign reg_in_o.main.LSR.THRE.next = !tx_fifo_thr_rvalid;
  assign reg_in_o.main.LSR.TEMT.next = !tx_fifo_thr_rvalid && tx_uart_idle;

  // Modem Status Register (MSR)
  // Modem status bits
  logic cts, cts_n;
  logic dsr, dsr_n;
  logic ri, ri_n;
  logic dcd, dcd_n;

  // Modem status bits input synchronization. The bits can change asynchronously.
  prim_flop_2sync #(
    .Width             (4),
    .ResetValue        (4'hf),
    .EnablePrimCdcRand (1'b1)
  ) u_flop_2sync_modem_status (
    .clk_i,
    .rst_ni,
    .d_i               ({cts_ni, dsr_ni, ri_ni, dcd_ni}),
    .q_o               ({cts_n,  dsr_n,  ri_n,  dcd_n})
  );

  // Modem status bits input mux
  always_comb begin
    if (sys_loopback) begin
      // In system loopback mode, the MSR bits are controlled by the MCR
      cts = rts;
      dsr = dtr;
      ri  = out1;
      dcd = out2;
    end else if (line_loopback) begin
      // In line loopback mode (if system loopback is disabled), the MSR bits are deasserted
      cts = 1'b0;
      dsr = 1'b0;
      ri  = 1'b0;
      dcd = 1'b0;
    end else begin
      // In normal mode, the MSR bits are controlled by the modem status inputs
      cts = ~cts_n;
      dsr = ~dsr_n;
      ri  = ~ri_n;
      dcd = ~dcd_n;
    end
  end

  assign reg_in_o.main.MSR.CTS.next = cts;
  assign reg_in_o.main.MSR.DSR.next = dsr;
  assign reg_in_o.main.MSR.RI.next  = ri;
  assign reg_in_o.main.MSR.DCD.next = dcd;

  // Modem status bits change detection
  logic msr_read;

  assign msr_read = reg_out_i.main.MSR.DCTS.rd_swacc;  // Use the SWACC property of the
                                                       // register's first field

  logic dcd_last_rd_val, dsr_last_rd_val, cts_last_rd_val;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      dcd_last_rd_val <= 1'b0;
      dsr_last_rd_val <= 1'b0;
      cts_last_rd_val <= 1'b0;
    end else if (msr_read) begin
      dcd_last_rd_val <= dcd;
      dsr_last_rd_val <= dsr;
      cts_last_rd_val <= cts;
    end
  end

  assign reg_in_o.main.MSR.DDCD.next = dcd != dcd_last_rd_val;
  assign reg_in_o.main.MSR.DDSR.next = dsr != dsr_last_rd_val;
  assign reg_in_o.main.MSR.DCTS.next = cts != cts_last_rd_val;

  logic ri_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      ri_q <= 1'b0;
    end else begin
      ri_q <= ri;
    end
  end

  assign reg_in_o.main.MSR.TERI.next = !ri && ri_q;

  assign intr_reqs.modem_status = (reg_out_i.main.MSR.intr || modem_status_intr_test) &&
                                    modem_status_intr_en;

  // Divisor Latch Registers (DLM and DLL)
  // Baud rate divisor configuration
  assign baud_rate_divisor = {reg_out_i.dl.DLM.DLM.value, reg_out_i.dl.DLL.DLL.value};

  // Disable TX and RX when Baud rate divisor is 0
  assign tx_enable = baud_rate_divisor != baud_cnt_t'(0);
  assign rx_enable = baud_rate_divisor != baud_cnt_t'(0);

  // Extended Control Register (ECR)
  // Extend RX FIFO trigger level configuration to 4 bits
  assign rx_trigger_level_ms2b = reg_out_i.main.ECR.RCVR_TRIGGER_MS2B.value;

  // Interrupt Test Register (ITR)
  assign receiver_line_status_intr_test               = reg_out_i.main.ITR.TLSI.value;
  assign reception_timeout_intr_test                  = reg_out_i.main.ITR.TRTI.value;
  assign received_data_ready_intr_test                = reg_out_i.main.ITR.TRBFI.value;
  assign transmitter_holding_register_empty_intr_test = reg_out_i.main.ITR.TTBEI.value;
  assign modem_status_intr_test                       = reg_out_i.main.ITR.TDSSI.value;
  assign fifo_error_intr_test                         = reg_out_i.main.ITR.TFEI.value;

endmodule
