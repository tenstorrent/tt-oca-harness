// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// UART 16550 Package
//
//-----------------------------------------------------------------------------

package uart_16550_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////
  // UART 16550 Definitions //
  ////////////////////////////

  localparam int unsigned MAX_FRAME_LEN = 12;
  localparam int unsigned TIMEOUT_CHAR_CNT = 4;  // Fixed by UART 16550


  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned REG_ADDR_WIDTH = uart_16550_main_reg_pkg::UART_16550_MAIN_REG_MIN_ADDR_WIDTH;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)


  //////////////////////////////
  // Register Map Definitions //
  //////////////////////////////

  localparam int unsigned NUM_REG_MAPS = 3;

  typedef enum logic [$clog2(
NUM_REG_MAPS
)-1:0] {
    MAIN_REG_MAP    = 2'd0,
    MAIN_WO_REG_MAP = 2'd1,
    DL_REG_MAP      = 2'd2
  } uart_16550_reg_map_e;

  typedef struct {
    uart_16550_main_reg_pkg::uart_16550_main__in_t       main;
    uart_16550_main_wo_reg_pkg::uart_16550_main_wo__in_t main_wo;
  } uart_16550_reg_in_t;

  typedef struct {
    uart_16550_main_reg_pkg::uart_16550_main__out_t       main;
    uart_16550_main_wo_reg_pkg::uart_16550_main_wo__out_t main_wo;
    uart_16550_dl_reg_pkg::uart_16550_dl__out_t           dl;
  } uart_16550_reg_out_t;


  /////////////////////////
  // TX & RX Definitions //
  /////////////////////////

  typedef enum bit {
    RX = 1'b0,
    TX = 1'b1
  } tx_rx_e;

  function automatic logic [3:0] get_word_length(logic [1:0] word_length_select);
    return 4'(5 + word_length_select);
  endfunction

  function automatic logic [3:0] get_frame_length(tx_rx_e tx_or_rx, logic [3:0] word_length,
                                                  logic extra_stop_bit, logic parity_en);
    logic [3:0] frame_length;
    frame_length = 4'd0;
    frame_length += 4'd1;  // 1 start bit
    frame_length += word_length;
    frame_length += 4'(parity_en);
    if (extra_stop_bit) begin
      if (word_length == 4'd5) begin
        // When word length = 5 and 1.5 stop bits is selected,
        // transmit 2 stop bits on the TX side, but only check for 1 stop bit on the RX side.
        frame_length += 4'(tx_or_rx == TX ? 2 : 1);
      end else begin
        frame_length += 4'd2;
      end
    end else begin
      frame_length += 4'd1;
    end
    return frame_length;
  endfunction

  function automatic logic [11:0] get_tx_frame_from_data(logic [7:0] tx_data, logic tx_parity,
                                                         logic [3:0] word_length, logic parity_en);
    logic [11:0] tx_frame;
    tx_frame = 12'({tx_data, 1'b0});
    // Plus 1 for start bit
    tx_frame |= 12'({5'h1f, parity_en ? tx_parity : 1'h1} << word_length + 1);
    return tx_frame;
  endfunction

  function automatic logic [7:0] get_rx_data_from_frame(
      logic [11:0] rx_frame, logic [3:0] word_length, logic extra_stop_bit, logic parity_en);
    logic [3:0] frame_length;
    logic [7:0] rx_data;
    frame_length = get_frame_length(RX, word_length, extra_stop_bit, parity_en);
    rx_data  = 8'(rx_frame >> 12 - frame_length + 1); // Plus 1 to shift out start bit
    rx_data &= 8'hff >> 8 - word_length;
    return rx_data;
  endfunction

  localparam int unsigned NUM_TRIGGER_LEVELS = 12; // 1, 4, 8, 14, 32, 64, 128, 256, 512, 1024, 2048, 4096

  typedef enum logic {
    DMA_MODE_0 = 1'b0,
    DMA_MODE_1 = 1'b1
  } dma_mode_e;


  ///////////////////////////
  // Interrupt Definitions //
  ///////////////////////////

  typedef enum logic [2:0] {
    FIFO_ERROR                         = 3'b111, // Highest priority
    RECEIVER_LINE_STATUS               = 3'b011,
    RECEPTION_TIMEOUT                  = 3'b110,
    RECEIVED_DATA_READY                = 3'b010,
    TRANSMITTER_HOLDING_REGISTER_EMPTY = 3'b001,
    MODEM_STATUS                       = 3'b000  // Lowest priority
  } interrupt_id_e;

  typedef struct packed {
    logic fifo_error;
    logic receiver_line_status;
    logic reception_timeout;
    logic received_data_ready;
    logic transmitter_holding_register_empty;
    logic modem_status;
  } interrupt_reqs_t;


  /////////////////////////
  // Utility Definitions //
  /////////////////////////

  function automatic bit is_pow_of_2(int unsigned num);
    return num > 0 && 2 ** $clog2(num) == num;
  endfunction

  function automatic logic [5:0] count_ones(logic [31:0] signal);
    logic [5:0] count = 6'd0;
    for (int i = 0; i < $bits(signal); i++) begin
      if (signal[i] == 1'b1) begin
        count += 6'd1;
      end
    end
    return count;
  endfunction

endpackage
