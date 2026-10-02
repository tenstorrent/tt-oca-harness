// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Drive the I2C controller FSM from the FMT FIFO onto SCL and SDA.
//
// Issues START and STOP around fmt_byte_i per FMT flags, waits while the target stretches
// SCL, and reports NAK, arbitration-loss, and stretch-timeout events.

module i2c_controller_fsm
  import i2c_pkg::*;
#(
  parameter  int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,    // FMT FIFO depth.
  localparam int unsigned ControllerTxFifoDepthWidth = $clog2(CONTROLLER_TX_FIFO_DEPTH + 1) // clog2(depth+1) for FMT fill.
) (
  input  logic                                      clk_i,  // System clock.
  input  logic                                      rst_ni, // Async reset, active-low.

  input  logic                                      scl_i,  // SCL pad input.
  output logic                                      scl_o,  // SCL pad output.
  input  logic                                      sda_i,  // SDA pad input.
  output logic                                      sda_o,  // SDA pad output.
  input  logic                                      bus_free_i, // Bus free for a new transfer.
  output logic                                      transmitting_o, // Controller is driving SDA.

  input  logic                                      host_enable_i, // Host/controller enable.
  input  logic                                      halt_controller_i, // Halt the controller FSM in IDLE.

  input  logic                                      fmt_fifo_rvalid_i, // FMT FIFO has valid data.
  input  logic [ControllerTxFifoDepthWidth-1:0]     fmt_fifo_depth_i, // FMT FIFO fill level.
  output logic                                      fmt_fifo_rready_o, // Pop FMT FIFO.
  input  logic [7:0]                                fmt_byte_i, // Byte in FMT FIFO to send to the
                                                                // target.
  input  logic                                      fmt_flag_start_before_i, // Issue START before sending the byte.
  input  logic                                      fmt_flag_stop_after_i, // Issue STOP after sending the byte.
  input  logic                                      fmt_flag_read_bytes_i, // Byte is a number of reads; zero means 256.
  input  logic                                      fmt_flag_read_continue_i, // Host sends Ack to the final read byte.
  input  logic                                      fmt_flag_nak_ok_i, // No ACK is expected.
  input  logic                                      unhandled_unexp_nak_i, // Unexpected-NACK IRQ still pending.
  input  logic                                      unhandled_nak_timeout_i, // NACK-handler timeout event not cleared.

  output logic                                      rx_fifo_wvalid_o, // Push a read byte into the RX FIFO.
  output logic [CONTROLLER_RX_FIFO_WIDTH-1:0]       rx_fifo_wdata_o, // Byte read from the target for the RX FIFO.

  output logic                                      host_idle_o, // Host is idle.

  input  logic [12:0]                               thigh_i, // SCL high period in clock units.
  input  logic [12:0]                               tlow_i, // SCL low period in clock units.
  input  logic [12:0]                               t_r_i,  // Rise time of SDA and SCL in clock
                                                            // units.
  input  logic [12:0]                               t_f_i,  // Fall time of SDA and SCL in clock
                                                            // units.
  input  logic [12:0]                               thd_sta_i, // Hold time for (repeated) START in
                                                               // clock units.
  input  logic [12:0]                               tsu_sta_i, // Setup time for repeated START in
                                                               // clock units.
  input  logic [12:0]                               tsu_sto_i, // Setup time for STOP in clock
                                                               // units.
  input  logic [12:0]                               thd_dat_i, // Data hold time in clock units.
  input  logic                                      sda_interference_i, // SCL high and SDA does not match while transmitting.
  input  logic [29:0]                               stretch_timeout_i, // Max clocks a target may stretch the clock.
  input  logic                                      timeout_enable_i, // Enables event_stretch_timeout_o.
  input  logic [30:0]                               host_nack_handler_timeout_i, // Clocks the FSM may stay halted on an unhandled
                                                                                 // Host-Mode NACK before it issues a STOP.
  input  logic                                      host_nack_handler_timeout_en_i, // Enable unhandled-NACK timeout.

  output logic                                      event_nak_o, // Target did not Ack when
                                                                 // expected.
  output logic                                      event_unhandled_nak_timeout_o, // SW did not handle the NACK in time; held while
                                                                                   // the FSM stays halted.
  output logic                                      event_arbitration_lost_o, // SDA unstable, SDA interference, or a failed START
                                                                              // or STOP symbol.
  output logic                                      event_scl_interference_o, // Other device forcing SCL low.
  output logic                                      event_stretch_timeout_o, // Target stretches clock past max time.
  output logic                                      event_sda_unstable_o, // SDA is not constant during an SCL pulse.
  output logic                                      event_cmd_complete_o // Command is complete.
);

  // I2C bus clock timing variables
  logic [13:0] tcount_q;                // Current counter for setting delays
  logic [13:0] tcount_d;                // Next counter for setting delays
  logic        load_tcount;             // Indicates counter must be loaded
  logic [30:0] stretch_idle_cnt;        // Counter for clock being stretched by target
                                        // or clock idle by host.
  logic [30:0] unhandled_nak_cnt;       // In Host-mode, count cycles where the FSM is halted awaiting
                                        // the NACK IRQ to be handled by SW.
  logic        incr_nak_cnt;

  // (IP in HOST-Mode) This bit is active when the FSM is in a state where a TARGET might
  // be trying to stretch the clock, preventing the controller FSM from continuing.
  logic        stretch_en;

  // Bit and byte counter variables
  logic [2:0]  bit_index;                // Bit being transmitted to or read from the bus
  logic        bit_decr;                 // Indicates bit_index must be decremented by 1
  logic        bit_clr;                  // Indicates bit_index must be reset to 7
  logic [8:0]  byte_num;                 // Number of bytes to read
  logic [8:0]  byte_index;               // Byte being read from the bus
  logic        byte_decr;                // Indicates byte_index must be decremented by 1
  logic        byte_clr;                 // Indicates byte_index must be reset to byte_num

  // Other internal variables
  logic        scl_d;                    // SCL internal
  logic        sda_d;                    // SDA internal
  logic        scl_i_q;                  // scl_i delayed by one clock
  logic        sda_i_q;                  // sda_i delayed by one clock
  logic [7:0]  read_byte;                // Register for reads from target
  logic        read_byte_clr;            // Clear read_byte contents
  logic        shift_data_en;            // Indicates data must be shifted in from the bus
  logic        trans_started;            // Indicates a transaction has started
  logic        pend_restart;             // There is a pending restart waiting to be processed
  logic        req_restart;              // Request restart
  logic        log_start;                // Indicates start is been issued
  logic        log_stop;                 // Indicates stop is been issued
  logic auto_stop_d, auto_stop_q;  // Tracks whether a Stop symbol was autonomously generated.
  logic ctrl_symbol_failed;  // If SCL pulls low before the controller can issue Start/Stop

  // Clock counter implementation
  typedef enum logic [3:0] {
    T_SETUP_START,
    T_HOLD_START,
    T_CLOCK_START,
    T_CLOCK_LOW,
    T_CLOCK_PULSE,
    T_CLOCK_HIGH,
    T_HOLD_BIT,
    T_CLOCK_STOP,
    T_SETUP_STOP,
    T_NO_DELAY
  } tcount_sel_e;

  tcount_sel_e tcount_sel;

  always_comb begin : counter_functions
    tcount_d = tcount_q;
    if (load_tcount) begin
      unique case (tcount_sel)
        T_SETUP_START : tcount_d = 13'(t_r_i) + 13'(tsu_sta_i);
        T_HOLD_START  : tcount_d = 13'(t_f_i) + 13'(thd_sta_i);
        T_CLOCK_START : tcount_d = 14'(thd_dat_i);
        T_CLOCK_LOW   : tcount_d = 13'(tlow_i) - 13'(thd_dat_i);
        T_CLOCK_PULSE : tcount_d = 13'(t_r_i) + 13'(thigh_i);
        T_CLOCK_HIGH  : tcount_d = 14'(thigh_i);
        T_HOLD_BIT    : tcount_d = 13'(t_f_i) + 13'(thd_dat_i);
        T_CLOCK_STOP  : tcount_d = 13'(t_f_i) + 13'(tlow_i) - 13'(thd_dat_i);
        T_SETUP_STOP  : tcount_d = 13'(t_r_i) + 13'(tsu_sto_i);
        T_NO_DELAY    : tcount_d = 14'h0001;
        default       : tcount_d = 14'h0001;
      endcase
    end else if (host_enable_i ||
        // If we disable Host-Mode mid-txn, keep counting until the end of
        // byte, at which point we create a STOP condition then return to IDLE.
        (!host_idle_o && !host_enable_i)) begin
      tcount_d = tcount_q - 1'b1;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin : clk_counter
    if (~rst_ni) begin
      tcount_q <= '1;
    end else begin
      tcount_q <= tcount_d;
    end
  end

  // Clock stretching/idle detection when i2c_ctrl.
  // When in host mode, this is a stretch count for how long an external target
  // has stretched the clock.
  // When in target mode, this is an idle count for how long an external host
  // has kept the clock idle after a START indication.
  always_ff @(posedge clk_i or negedge rst_ni) begin : clk_stretch
    if (~rst_ni) begin
      stretch_idle_cnt <= '0;
    end else if (stretch_en && !scl_i) begin
      // HOST-mode count of clock stretching
      stretch_idle_cnt <= stretch_idle_cnt + 1'b1;
    end else begin
      stretch_idle_cnt <= '0;
    end
  end

  // The TARGET can stretch the clock during any time that the host drives SCL to 0.
  // However, we (the HOST) cannot know it is being stretched until we release SCL,
  // usually trying to create the next clock pulse.
  // There is a minimum 3-cycle round trip (1-cycle output flop, 2-cycle input synchronizer),
  // between releasing the clock and observing the effect of releasing the clock on
  // the inputs. However, this is really '1 + t_r + 2' as the bus also needs to slew to '1
  // before can observe it. Even if the TARGET is not stretching the clock, we cannot
  // confirm it until at-least this amount of time has elapsed.
  //
  // 'stretch_predict_cnt_expired' becomes active once we have observed (4 + t_r) cycles of
  // delay, and if !scl_i at this point we know that the TARGET is stretching the clock.
  // > This implementation requires 'thigh >= 4' to guarantee we don't miss stretching.
  logic [30:0] stretch_cnt_threshold;
  assign stretch_cnt_threshold = 31'd2 + 31'(t_r_i);

  logic stretch_predict_cnt_expired;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      stretch_predict_cnt_expired <= 1'b0;
    end else begin
      if (stretch_idle_cnt == stretch_cnt_threshold) begin
        stretch_predict_cnt_expired <= 1'b1;
      end else if (!stretch_en) begin
        stretch_predict_cnt_expired <= 1'b0;
      end
    end
  end

  // While the FSM is halted due to an unhandled 'nak' irq in Host-Mode, this counter can
  // be used to trigger a timeout which disables Host-Mode and creates a STOP condition to
  // end the transaction.
  logic unhandled_nak_cnt_expired;
  always_ff @(posedge clk_i or negedge rst_ni) begin : unhandled_nak_cnt_b
    if (~rst_ni) begin
      unhandled_nak_cnt <= '0;
      unhandled_nak_cnt_expired <= 1'b0;
    end else if (incr_nak_cnt) begin
      // Increment the counter while the FSM is halted in IDLE.
      unhandled_nak_cnt <= unhandled_nak_cnt + 1'b1;
      if (unhandled_nak_cnt > host_nack_handler_timeout_i) begin
        unhandled_nak_cnt_expired <= 1'b1;
      end
    end else begin
      unhandled_nak_cnt <= '0;
      unhandled_nak_cnt_expired <= 1'b0;
    end
  end

  assign event_unhandled_nak_timeout_o = unhandled_nak_cnt_expired;

  // Bit index implementation
  always_ff @(posedge clk_i or negedge rst_ni) begin : bit_counter
    if (~rst_ni) begin
      bit_index <= 3'd7;
    end else if (bit_clr) begin
      bit_index <= 3'd7;
    end else if (bit_decr) begin
      bit_index <= bit_index - 1'b1;
    end else begin
      bit_index <= bit_index;
    end
  end

  // Deserializer for a byte read from the bus
  always_ff @(posedge clk_i or negedge rst_ni) begin : read_register
    if (~rst_ni) begin
      read_byte <= 8'h00;
    end else if (read_byte_clr) begin
      read_byte <= 8'h00;
    end else if (shift_data_en) begin
      read_byte[7:0] <= {read_byte[6:0], sda_i};  // MSB goes in first
    end
  end

  // Number of bytes to read
  always_comb begin : byte_number
    if (!fmt_flag_read_bytes_i) byte_num = 9'd0;
    else if (fmt_byte_i == '0) byte_num = 9'd256;
    else byte_num = 9'(fmt_byte_i);
  end

  // Byte index implementation
  always_ff @(posedge clk_i or negedge rst_ni) begin : byte_counter
    if (~rst_ni) begin
      byte_index <= '0;
    end else if (byte_clr) begin
      byte_index <= byte_num;
    end else if (byte_decr) begin
      byte_index <= byte_index - 1'b1;
    end else begin
      byte_index <= byte_index;
    end
  end

  // SDA and SCL at the previous clock edge
  always_ff @(posedge clk_i or negedge rst_ni) begin : bus_prev
    if (~rst_ni) begin
      scl_i_q <= 1'b1;
      sda_i_q <= 1'b1;
    end else begin
      scl_i_q <= scl_i;
      sda_i_q <= sda_i;
    end
  end

  // SCL going low early is just clock synchronization. SCL switching so fast that the controller
  // can't even sense its outputs is cause for a bus error.
  assign event_arbitration_lost_o = event_sda_unstable_o || sda_interference_i ||
                                      ctrl_symbol_failed;

  // Registers whether a transaction start has been observed.
  // A transaction start does not include a "restart", but rather
  // the first start after enabling i2c, or a start observed after a
  // stop.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      trans_started <= '0;
    end else if (trans_started && (!host_enable_i || event_arbitration_lost_o)) begin
      trans_started <= '0;
    end else if (log_start) begin
      trans_started <= 1'b1;
    end else if (log_stop) begin
      trans_started <= 1'b0;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      pend_restart <= '0;
    end else if (pend_restart && !host_enable_i) begin
      pend_restart <= '0;
    end else if (req_restart) begin
      pend_restart <= 1'b1;
    end else if (log_start) begin
      pend_restart <= '0;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      auto_stop_q <= 1'b0;
    end else begin
      auto_stop_q <= auto_stop_d;
    end
  end

  // State definitions
  typedef enum logic [4:0] {
    IDLE,
    ///////////////////////
    // Host function states
    ///////////////////////
    ACTIVE,
    POP_FMT_FIFO,
    // Host function starts a transaction
    SETUP_START,
    HOLD_START,
    CLOCK_START,
    // Host function stops a transaction
    SETUP_STOP,
    HOLD_STOP,
    CLOCK_STOP,
    // Host function transmits a bit to the external target
    CLOCK_LOW,
    CLOCK_PULSE,
    HOLD_BIT,
    // Host function receives an ack from the external target
    CLOCK_LOW_ACK,
    CLOCK_PULSE_ACK,
    HOLD_DEV_ACK,
    // Host function reads a bit from the external target
    READ_CLOCK_LOW,
    READ_CLOCK_PULSE,
    READ_HOLD_BIT,
    // Host function transmits an ack to the external target
    HOST_CLOCK_LOW_ACK,
    HOST_CLOCK_PULSE_ACK,
    HOST_HOLD_BIT_ACK
  } state_e;

  state_e state_q, state_d;


  // Increment the NACK timeout count if the controller is halted in IDLE and
  // the timeout hasn't yet occurred.
  assign incr_nak_cnt = unhandled_unexp_nak_i && host_enable_i && (state_q == IDLE) &&
                          host_nack_handler_timeout_en_i && !unhandled_nak_timeout_i;

  // Outputs for each state
  always_comb begin : state_outputs
    host_idle_o = 1'b1;
    sda_d = 1'b1;
    scl_d = 1'b1;
    transmitting_o = 1'b0;
    log_start = 1'b0;
    log_stop = 1'b0;
    fmt_fifo_rready_o = 1'b0;
    rx_fifo_wvalid_o = 1'b0;
    rx_fifo_wdata_o = CONTROLLER_RX_FIFO_WIDTH'(0);
    event_nak_o = 1'b0;
    event_scl_interference_o = 1'b0;
    ctrl_symbol_failed = 1'b0;
    event_sda_unstable_o = 1'b0;
    event_cmd_complete_o = 1'b0;
    stretch_en = 1'b0;
    unique case (state_q)
      // IDLE: initial state, SDA is released (high), SCL is released if the
      // bus is idle. Otherwise, if no STOP condition has been sent yet,
      // continue pulling SCL low in host mode.
      IDLE: begin
        sda_d = 1'b1;
        if (trans_started) begin
          host_idle_o = 1'b0;
          scl_d = 1'b0;
        end else begin
          host_idle_o = 1'b1;
          scl_d = 1'b1;
        end
      end

      ///////////////
      // HOST MODE //
      ///////////////

      // SETUP_START: SDA and SCL are released
      SETUP_START: begin
        host_idle_o = 1'b0;
        sda_d = 1'b1;
        scl_d = 1'b1;
        transmitting_o = 1'b1;
        // If this is a restart, SCL was last low, and a target could be stretching the clock.
        stretch_en = trans_started;
        if (trans_started && !scl_i && scl_i_q) begin
          // If this is a repeated Start, an early clock prevents issuing the symbol. If it's not
          // a repeated start, the FSM will just go back to IDLE and wait for the bus to go free
          // again.
          ctrl_symbol_failed = 1'b1;
        end else if (tcount_q == 20'd1) begin
          log_start = 1'b1;
          event_cmd_complete_o = pend_restart;
        end
      end
      // HOLD_START: SDA is pulled low, SCL is released
      HOLD_START: begin
        host_idle_o = 1'b0;
        sda_d = 1'b0;
        scl_d = 1'b1;
        transmitting_o = 1'b1;
        if (scl_i_q && !scl_i) begin
          event_scl_interference_o = 1'b1;
        end
      end
      // CLOCK_START: SCL is pulled low, SDA stays low
      CLOCK_START: begin
        host_idle_o = 1'b0;
        sda_d = 1'b0;
        scl_d = 1'b0;
        transmitting_o = 1'b1;
      end
      CLOCK_LOW: begin
        host_idle_o = 1'b0;
        if (pend_restart) begin
          sda_d = 1'b1;
        end else begin
          sda_d = fmt_byte_i[bit_index];
        end
        scl_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // CLOCK_PULSE: SCL is released, SDA keeps the indexed bit value
      CLOCK_PULSE: begin
        host_idle_o = 1'b0;
        sda_d = fmt_byte_i[bit_index];
        scl_d = 1'b1;
        transmitting_o = 1'b1;
        stretch_en = 1'b1;
        if (scl_i_q && !scl_i) begin
          event_scl_interference_o = 1'b1;
        end
        if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          event_sda_unstable_o = 1'b1;
        end
      end
      // HOLD_BIT: SCL is pulled low
      HOLD_BIT: begin
        host_idle_o = 1'b0;
        sda_d = fmt_byte_i[bit_index];
        scl_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // CLOCK_LOW_ACK: SCL pulled low, SDA is released
      CLOCK_LOW_ACK: begin
        host_idle_o = 1'b0;
        sda_d = 1'b1;
        scl_d = 1'b0;
      end
      // CLOCK_PULSE_ACK: SCL is released
      CLOCK_PULSE_ACK: begin
        host_idle_o = 1'b0;
        sda_d = 1'b1;
        scl_d = 1'b1;
        if (!scl_i_q && scl_i && sda_i && !fmt_flag_nak_ok_i) begin
          event_nak_o = 1'b1;
        end
        stretch_en = 1'b1;
        if (scl_i_q && !scl_i) begin
          event_scl_interference_o = 1'b1;
        end
        if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          event_sda_unstable_o = 1'b1;
        end
      end
      // HOLD_DEV_ACK: SCL is pulled low
      HOLD_DEV_ACK: begin
        host_idle_o = 1'b0;
        sda_d = 1'b1;
        scl_d = 1'b0;
      end
      // READ_CLOCK_LOW: SCL is pulled low, SDA is released
      READ_CLOCK_LOW: begin
        host_idle_o = 1'b0;
        sda_d = 1'b1;
        scl_d = 1'b0;
      end
      // READ_CLOCK_PULSE: SCL is released, the indexed bit value is read off SDA
      READ_CLOCK_PULSE: begin
        host_idle_o = 1'b0;
        scl_d = 1'b1;
        stretch_en = 1'b1;
        if (scl_i_q && !scl_i) begin
          event_scl_interference_o = 1'b1;
        end
        if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          event_sda_unstable_o = 1'b1;
        end
      end
      // READ_HOLD_BIT: SCL is pulled low
      READ_HOLD_BIT: begin
        host_idle_o = 1'b0;
        scl_d = 1'b0;
        if (bit_index == '0 && tcount_q == 20'd1) begin
          rx_fifo_wvalid_o = 1'b1;     // assert that rx_fifo has valid data
          rx_fifo_wdata_o = read_byte; // transfer read data to rx_fifo
        end
      end
      // HOST_CLOCK_LOW_ACK: SCL pulled low, SDA is conditional
      HOST_CLOCK_LOW_ACK: begin
        host_idle_o = 1'b0;
        scl_d = 1'b0;
        transmitting_o = 1'b1;

        // If it is the last byte of a read, send a NAK before the stop.
        // Otherwise send the ack.
        if (fmt_flag_read_continue_i) begin
          sda_d = 1'b0;
        end else if (byte_index == 9'd1) begin
          sda_d = 1'b1;
        end else begin
          sda_d = 1'b0;
        end
      end
      // HOST_CLOCK_PULSE_ACK: SCL is released
      HOST_CLOCK_PULSE_ACK: begin
        host_idle_o = 1'b0;
        if (fmt_flag_read_continue_i) begin
          sda_d = 1'b0;
        end else if (byte_index == 9'd1) begin
          sda_d = 1'b1;
        end else begin
          sda_d = 1'b0;
        end
        scl_d = 1'b1;
        transmitting_o = 1'b1;
        stretch_en = 1'b1;
        if (scl_i_q && !scl_i) begin
          event_scl_interference_o = 1'b1;
        end
        if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          event_sda_unstable_o = 1'b1;
        end
      end
      // HOST_HOLD_BIT_ACK: SCL is pulled low
      HOST_HOLD_BIT_ACK: begin
        host_idle_o = 1'b0;
        if (fmt_flag_read_continue_i) begin
          sda_d = 1'b0;
        end else if (byte_index == 9'd1) begin
          sda_d = 1'b1;
        end else begin
          sda_d = 1'b0;
        end
        scl_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // CLOCK_STOP: SCL is pulled low, SDA stays low
      CLOCK_STOP: begin
        host_idle_o = 1'b0;
        sda_d = 1'b0;
        scl_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // SETUP_STOP: SDA is pulled low, SCL is released
      SETUP_STOP: begin
        host_idle_o = 1'b0;
        sda_d = 1'b0;
        scl_d = 1'b1;
        transmitting_o = 1'b1;
        stretch_en = 1'b1;
        if (!scl_i && scl_i_q) begin
          // Failed to issue Stop before some other device could pull SCL low.
          ctrl_symbol_failed = 1'b1;
        end
      end
      // HOLD_STOP: SDA and SCL are released
      HOLD_STOP: begin
        host_idle_o = 1'b0;
        sda_d = 1'b1;
        scl_d = 1'b1;
        event_cmd_complete_o = 1'b1;
        if (!sda_i && !scl_i) begin
          // Failed to issue Stop before some other device could pull SCL low.
          ctrl_symbol_failed = 1'b1;
        end else if (sda_i) begin
          log_stop = 1'b1;
        end
      end
      // ACTIVE: continue while keeping SCL low
      ACTIVE: begin
        host_idle_o = 1'b0;

        // If this is a transaction start, do not drive scl low
        // since in the next state we will drive it high to initiate
        // the start bit.
        // If this is a restart, continue driving the clock low.
        scl_d = fmt_flag_start_before_i && !trans_started;
      end
      // POP_FMT_FIFO: populate fmt_fifo
      POP_FMT_FIFO: begin
        host_idle_o = 1'b0;
        if (fmt_flag_stop_after_i) begin
          scl_d = 1'b1;
        end else begin
          scl_d = 1'b0;
        end
        fmt_fifo_rready_o = 1'b1;
      end

      // default
      default: begin
        host_idle_o = 1'b1;
        sda_d = 1'b1;
        scl_d = 1'b1;
        transmitting_o = 1'b0;
        log_start = 1'b0;
        log_stop = 1'b0;
        event_scl_interference_o = 1'b0;
        ctrl_symbol_failed = 1'b0;
        fmt_fifo_rready_o = 1'b0;
        rx_fifo_wvalid_o = 1'b0;
        rx_fifo_wdata_o = CONTROLLER_RX_FIFO_WIDTH'(0);
        event_nak_o = 1'b0;
        event_sda_unstable_o = 1'b0;
        event_cmd_complete_o = 1'b0;
      end
    endcase  // unique case (state_q)
  end

  // Conditional state transition
  always_comb begin : state_functions
    state_d = state_q;
    load_tcount = 1'b0;
    tcount_sel = T_NO_DELAY;
    bit_decr = 1'b0;
    bit_clr = 1'b0;
    byte_decr = 1'b0;
    byte_clr = 1'b0;
    read_byte_clr = 1'b0;
    shift_data_en = 1'b0;
    req_restart = 1'b0;
    auto_stop_d = auto_stop_q;

    unique case (state_q)
      // IDLE: initial state, SDA is released (high), and SCL is released if there is no ongoing
      // transaction.
      IDLE: begin
        if (host_enable_i) begin
          if (unhandled_unexp_nak_i || unhandled_nak_timeout_i || halt_controller_i) begin
            // If we are awaiting software to handle an unexpected NACK, halt the FSM here.
            // The current transaction does not end, and SCL remains in its current state.
            // Software typically should handle an unexpected NACK by either disabling the
            // controller (causing host_enable_i to fall) or by the following sequence:
            //   1. Clear and/or populate the FMT FIFO.
            //   2. Clear CONTROLLER_EVENTS.NACK
            // Note that if the timeout feature is enabled, the controller will be forced to
            // issue a Stop if software takes too long to address the NACK. A short timeout
            // could also be used to automatically issue a Stop whenever an unexpected NACK
            // occurs.
            // Note that we may also halt here on a bus timeout or if arbitration was lost, so
            // software may fix up the FIFOs before beginning a new transaction.
            if (trans_started && unhandled_nak_cnt_expired) begin
              // If our timeout counter expires, generate a STOP condition automatically.
              auto_stop_d = 1'b1;
              state_d = CLOCK_STOP;
              load_tcount = 1'b1;
              tcount_sel = T_CLOCK_STOP;
            end
          end else if (fmt_fifo_rvalid_i) begin
            if (trans_started || bus_free_i) begin
              state_d = ACTIVE;
            end
          end
        end else if (trans_started && !host_enable_i) begin
          auto_stop_d = 1'b1;
          state_d = CLOCK_STOP;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_STOP;
        end
      end

      ///////////////
      // HOST MODE //
      ///////////////

      // SETUP_START: SDA and SCL are released
      SETUP_START: begin
        if (!trans_started && !scl_i) begin
          // This was the start of a transaction, but another device beat us to access. Go back to
          // IDLE, and wait for the next turn.
          state_d = IDLE;
        end else if (trans_started && !scl_i && !scl_i_q && stretch_predict_cnt_expired) begin
          // Saw stretching. Remain in this state and don't count down until we see SCL high.
          state_d = SETUP_START;
          load_tcount = 1'b1;
          // This double-counts the rise time, unfortunately.
          tcount_sel = T_SETUP_START;
        end else if (trans_started && !scl_i && scl_i_q) begin
          // Failed to issue repeated Start. Effectively lost arbitration.
          state_d = IDLE;
        end else if (tcount_q == 20'd1) begin
          state_d = HOLD_START;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_START;
        end
      end
      // HOLD_START: SDA is pulled low, SCL is released
      HOLD_START: begin
        if (tcount_q == 20'd1 || (!scl_i && scl_i_q)) begin
          state_d = CLOCK_START;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_START;
        end
      end
      // CLOCK_START: SCL is pulled low, SDA stays low
      CLOCK_START: begin
        if (tcount_q == 20'd1) begin
          state_d = CLOCK_LOW;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_LOW;
        end
      end
      // CLOCK_LOW: SCL stays low, shift indexed bit onto SDA
      CLOCK_LOW: begin
        if (tcount_q == 20'd1) begin
          load_tcount = 1'b1;
          if (pend_restart) begin
            state_d = SETUP_START;
            tcount_sel = T_SETUP_START;
          end else begin
            state_d = CLOCK_PULSE;
            tcount_sel = T_CLOCK_PULSE;
          end
        end
      end
      // CLOCK_PULSE: SCL is released, SDA keeps the indexed bit value
      CLOCK_PULSE: begin
        if (!scl_i && !scl_i_q && stretch_predict_cnt_expired) begin
          // Saw stretching. Remain in this state and don't count down until we see SCL high.
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_HIGH;
        end else if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          state_d = IDLE;
        end else if (tcount_q == 20'd1 || (!scl_i && scl_i_q)) begin
          // Transition either when we finish counting our high period or
          // another controller pulls clock low.
          state_d = HOLD_BIT;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_BIT;
        end
      end
      // HOLD_BIT: SCL is pulled low
      HOLD_BIT: begin
        if (tcount_q == 20'd1) begin
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_LOW;
          if (bit_index == '0) begin
            state_d = CLOCK_LOW_ACK;
            bit_clr = 1'b1;
          end else begin
            state_d = CLOCK_LOW;
            bit_decr = 1'b1;
          end
        end
      end
      // CLOCK_LOW_ACK: Target is allowed to drive ack back
      // to host (dut)
      CLOCK_LOW_ACK: begin
        if (tcount_q == 20'd1) begin
          state_d = CLOCK_PULSE_ACK;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_PULSE;
        end
      end
      // CLOCK_PULSE_ACK: SCL is released
      CLOCK_PULSE_ACK: begin
        if (!scl_i && !scl_i_q && stretch_predict_cnt_expired) begin
          // Saw stretching. Remain in this state and don't count down until we see SCL high.
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_HIGH;
        end else if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          state_d = IDLE;
        end else begin
          if (tcount_q == 20'd1 || (!scl_i && scl_i_q)) begin
            state_d = HOLD_DEV_ACK;
            load_tcount = 1'b1;
            tcount_sel = T_HOLD_BIT;
          end
        end
      end
      // HOLD_DEV_ACK: SCL is pulled low
      HOLD_DEV_ACK: begin
        if (tcount_q == 20'd1) begin
          if (fmt_flag_stop_after_i) begin
            state_d = CLOCK_STOP;
            load_tcount = 1'b1;
            tcount_sel = T_CLOCK_STOP;
          end else begin
            state_d = POP_FMT_FIFO;
            load_tcount = 1'b1;
            tcount_sel = T_NO_DELAY;
          end
        end
      end
      // READ_CLOCK_LOW: SCL is pulled low, SDA is released
      READ_CLOCK_LOW: begin
        if (tcount_q == 20'd1) begin
          state_d = READ_CLOCK_PULSE;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_PULSE;
        end
      end
      // READ_CLOCK_PULSE: SCL is released, the indexed bit value is read off SDA
      READ_CLOCK_PULSE: begin
        if (!scl_i && !scl_i_q && stretch_predict_cnt_expired) begin
          // Saw stretching. Remain in this state and don't count down until we see SCL high.
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_HIGH;
        end else if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          state_d = IDLE;
        end else if (tcount_q == 20'd1 || (!scl_i && scl_i_q)) begin
          state_d = READ_HOLD_BIT;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_BIT;
          shift_data_en = 1'b1; // SDA is sampled on the final clk_i cycle of the SCL pulse.
        end
      end
      // READ_HOLD_BIT: SCL is pulled low
      READ_HOLD_BIT: begin
        if (tcount_q == 20'd1) begin
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_LOW;
          if (bit_index == '0) begin
            state_d = HOST_CLOCK_LOW_ACK;
            bit_clr = 1'b1;
            read_byte_clr = 1'b1;
          end else begin
            state_d = READ_CLOCK_LOW;
            bit_decr = 1'b1;
          end
        end
      end
      // HOST_CLOCK_LOW_ACK: SCL is pulled low, SDA is conditional based on
      // byte position
      HOST_CLOCK_LOW_ACK: begin
        if (tcount_q == 20'd1) begin
          state_d = HOST_CLOCK_PULSE_ACK;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_PULSE;
        end
      end
      // HOST_CLOCK_PULSE_ACK: SCL is released
      HOST_CLOCK_PULSE_ACK: begin
        if (!scl_i && !scl_i_q && stretch_predict_cnt_expired) begin
          // Saw stretching. Remain in this state and don't count down until we see SCL high.
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_HIGH;
        end else if (scl_i_q && scl_i && (sda_i_q != sda_i)) begin
          // Unexpected Stop / Start
          state_d = IDLE;
        end else if (tcount_q == 20'd1 || (!scl_i && scl_i_q)) begin
          state_d = HOST_HOLD_BIT_ACK;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_BIT;
        end
      end
      // HOST_HOLD_BIT_ACK: SCL is pulled low
      HOST_HOLD_BIT_ACK: begin
        if (tcount_q == 20'd1) begin
          if (byte_index == 9'd1) begin
            if (fmt_flag_stop_after_i) begin
              state_d = CLOCK_STOP;
              load_tcount = 1'b1;
              tcount_sel = T_CLOCK_STOP;
            end else begin
              state_d = POP_FMT_FIFO;
              load_tcount = 1'b1;
              tcount_sel = T_NO_DELAY;
            end
          end else begin
            state_d = READ_CLOCK_LOW;
            load_tcount = 1'b1;
            tcount_sel = T_CLOCK_LOW;
            byte_decr = 1'b1;
          end
        end
      end
      // CLOCK_STOP: SCL is pulled low, SDA stays low
      CLOCK_STOP: begin
        if (tcount_q == 20'd1) begin
          state_d = SETUP_STOP;
          load_tcount = 1'b1;
          tcount_sel = T_SETUP_STOP;
        end
      end
      // SETUP_STOP: SDA is pulled low, SCL is released
      SETUP_STOP: begin
        if (!scl_i && !scl_i_q && stretch_predict_cnt_expired) begin
          // Saw stretching. Remain in this state and don't count down until we see SCL high.
          load_tcount = 1'b1;
          tcount_sel = T_SETUP_STOP;
        end else if (!scl_i && scl_i_q) begin
          // Failed to issue Stop before some other device could pull SCL low.
          state_d = IDLE;
        end else if (tcount_q == 20'd1) begin
          state_d = HOLD_STOP;
        end
      end
      // HOLD_STOP: SDA and SCL are released
      HOLD_STOP: begin
        if (!sda_i && !scl_i) begin
          // Failed to issue Stop before some other device could pull SCL low.
          state_d = IDLE;
          auto_stop_d = 1'b0;
        end else if (sda_i) begin
          auto_stop_d = 1'b0;
          if (auto_stop_q) begin
            // If this Stop symbol was generated automatically, go back to IDLE.
            state_d = IDLE;
            load_tcount = 1'b1;
            tcount_sel = T_NO_DELAY;
          end else begin
            state_d = POP_FMT_FIFO;
            load_tcount = 1'b1;
            tcount_sel = T_NO_DELAY;
          end
        end
      end
      // ACTIVE: continue while keeping SCL low
      ACTIVE: begin
        if (fmt_flag_read_bytes_i) begin
          byte_clr = 1'b1;
          state_d = READ_CLOCK_LOW;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_LOW;
        end else if (fmt_flag_start_before_i && !trans_started) begin
          state_d = SETUP_START;
          load_tcount = 1'b1;
          tcount_sel = T_SETUP_START;
        end else begin
          state_d = CLOCK_LOW;
          load_tcount = 1'b1;
          req_restart = fmt_flag_start_before_i;
          tcount_sel = T_CLOCK_LOW;
        end
      end
      // POP_FMT_FIFO: pop fmt_fifo item
      POP_FMT_FIFO: begin
        if (!host_enable_i && trans_started) begin
          auto_stop_d = 1'b1;
          state_d = CLOCK_STOP;
          load_tcount = 1'b1;
          tcount_sel = T_CLOCK_STOP;
        end else if (!host_enable_i || (fmt_fifo_depth_i == 7'h1) ||
                             unhandled_unexp_nak_i || !trans_started) begin
          state_d = IDLE;
          load_tcount = 1'b1;
          tcount_sel = T_NO_DELAY;
        end else begin
          state_d = ACTIVE;
          load_tcount = 1'b1;
          tcount_sel = T_NO_DELAY;
        end
      end

      // default
      default: begin
        state_d = IDLE;
        load_tcount = 1'b0;
        tcount_sel = T_NO_DELAY;
        bit_decr = 1'b0;
        bit_clr = 1'b0;
        byte_decr = 1'b0;
        byte_clr = 1'b0;
        read_byte_clr = 1'b0;
        shift_data_en = 1'b0;
        auto_stop_d = 1'b0;
      end
    endcase  // unique case (state_q)

    if (trans_started && (sda_interference_i || ctrl_symbol_failed)) begin
      state_d = IDLE;
    end
  end

  // Synchronous state transition
  always_ff @(posedge clk_i or negedge rst_ni) begin : state_transition
    if (~rst_ni) begin
      state_q <= IDLE;
    end else begin
      state_q <= state_d;
    end
  end

  assign scl_o = scl_d;
  assign sda_o = sda_d;

  // Target stretched clock beyond timeout
  assign event_stretch_timeout_o = stretch_en && timeout_enable_i &&
                                    (stretch_idle_cnt > 31'(stretch_timeout_i));

  // Make sure we never attempt to send a single cycle glitch
  `OCAH_OT_ASSERT(SclOutputGlitch_A, $rose(scl_o) |-> ##1 scl_o)

endmodule
