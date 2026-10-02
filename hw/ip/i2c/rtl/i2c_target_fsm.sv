// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Answer matched I2C addresses in the target FSM and fill the ACQ FIFO.
//
// Drives SCL stretch for TX underrun, a nearly full ACQ FIFO and ACK-control mode, applies
// address masks, and pulses events for match, NACK, unexpected STOP, and arbitration loss.

module i2c_target_fsm
  import i2c_pkg::*;
#(
  parameter  int unsigned TARGET_RX_FIFO_DEPTH = 64,        // ACQ FIFO depth.
  localparam int unsigned TARGET_RX_FIFO_DEPTH_WIDTH = $clog2(TARGET_RX_FIFO_DEPTH+1) // clog2(depth+1) for ACQ fill.
) (
  input  logic                                  clk_i,      // System clock.
  input  logic                                  rst_ni,     // Async reset, active-low.

  input  logic                                  scl_i,      // Serial clock input from the I2C bus.
  output logic                                  scl_o,      // Serial clock output to the I2C bus.
  input  logic                                  sda_i,      // Serial data input from the I2C bus.
  output logic                                  sda_o,      // Serial data output to the I2C bus.
  input  logic                                  start_detect_i, // START from the bus monitor.
  input  logic                                  stop_detect_i, // STOP from the bus monitor.
  output logic                                  transmitting_o, // Target is transmitting SDA
                                                                // (disambiguates high sda_o).

  input  logic                                  target_enable_i, // Enable target functionality.

  input  logic                                  tx_fifo_rvalid_i, // TX FIFO has valid data.
  output logic                                  tx_fifo_rready_o, // Pop entry from TX FIFO.
  input  logic [TARGET_TX_FIFO_WIDTH-1:0]       tx_fifo_rdata_i, // Byte in TX FIFO to send to the
                                                                 // host.

  output logic                                  acq_fifo_wvalid_o, // Push valid data into the ACQ
                                                                   // FIFO.
  output logic [TARGET_RX_FIFO_WIDTH-1:0]       acq_fifo_wdata_o, // Data to write to the ACQ FIFO.
  input  logic [TARGET_RX_FIFO_DEPTH_WIDTH-1:0] acq_fifo_depth_i, // Fill level of the ACQ FIFO.
  output logic                                  acq_fifo_full_o, // High while two or fewer ACQ FIFO
                                                                 // entries are free.
  input  logic [TARGET_RX_FIFO_WIDTH-1:0]       acq_fifo_rdata_i, // ACQ peek used only for
                                                                  // assertions.

  output logic                                  target_idle_o, // Target is idle.

  input logic [12:0]                            t_r_i,      // Rise time of SDA and SCL in clock
                                                            // units.
  input logic [12:0]                            tsu_dat_i,  // Data setup time in clock units.
  input logic [12:0]                            thd_dat_i,  // Data hold time in clock units.
  input logic [30:0]                            nack_timeout_i, // Max time the target may stretch
                                                                // until it should NACK.
  input logic                                   nack_timeout_en_i, // Enable NACK timeout.
  input logic                                   nack_addr_after_timeout_i, // NACK address after timeout.
  input logic                                   arbitration_lost_i, // Lost arbitration while transmitting.
  input logic                                   bus_timeout_i, // Bus timed out with SCL held low
                                                               // too long.

  input logic                                   unhandled_tx_stretch_event_i, // Unhandled event requests TX stretching.

  input  logic                                  ack_ctrl_mode_i, // ACK Control Mode enabled.
  input  logic                                  acq_start_stop_en_i, // Enable START/STOP in the ACQ FIFO.
  input  logic [8:0]                            auto_ack_cnt_i, // Current TARGET_ACK_CTRL.NBYTES
                                                                // counter value.
  output logic                                  auto_ack_cnt_clr_o, // Clear the TARGET_ACK_CTRL.NBYTES counter.
  output logic                                  auto_ack_cnt_decr_o, // Decrement the TARGET_ACK_CTRL.NBYTES counter.
  input  logic                                  sw_nack_i,  // SW pulses high to NACK while
                                                            // stretching in ack_ctrl.
  output logic                                  ack_ctrl_stretching_o, // Stretching due to zero Auto ACK count.
  output logic [7:0]                            acq_fifo_next_data_o, // Next data byte for SW NACK decisions.

  input  logic [6:0]                            target_address0_i, // Address 0.
  input  logic [6:0]                            target_mask0_i, // Address 0 mask; zero disables
                                                                // address 0.
  input  logic [6:0]                            target_address1_i, // Address 1.
  input  logic [6:0]                            target_mask1_i, // Address 1 mask; zero disables
                                                                // address 1.

  output logic                                  event_address_match_o, // One of the target addresses matched.
  output logic                                  event_target_nack_o, // This target sent a NACK.
  output logic                                  event_cmd_complete_o, // Command is complete.
  output logic                                  event_tx_stretch_o, // TX transaction is being stretched.
  output logic                                  event_unexp_stop_o, // STOP during a read addressed to this target without a
                                                                    // preceding host NACK.
  output logic                                  event_tx_arbitration_lost_o, // Arbitration was lost during a read transfer.
  output logic                                  event_tx_bus_timeout_o, // Bus timed out during a read transfer.
  output logic                                  event_read_cmd_received_o // A read awaits confirmation for TX FIFO release.
);

  // I2C bus clock timing variables
  logic [13:0] tcount_q;                       // Current counter for setting delays
  logic [13:0] tcount_d;                       // Next counter for setting delays
  logic        load_tcount;                    // Indicates counter must be loaded
  logic [30:0] stretch_active_cnt;             // In target mode keep track of how long it has stretched for
                                               // The NACK timeout feature.

  logic        actively_stretching;            // Only high when this target is holding SCL low to stretch.
  logic        ack_ctrl_stretching;            // Stretching due to Auto ACK Count exhausted

  logic        nack_transaction_q;             // Set if the rest of the transaction needs to be nack'd.
  logic        nack_transaction_d;

  // Other internal variables
  logic        scl_d;                          // SCL Internal
  logic sda_d, sda_q;  // SDA Internal
  logic        scl_i_q;                        // scl_i delayed by one clock

  // Target specific variables
  logic        restart_det_q;                  // Indicates the latest start was a repeated start
  logic        restart_det_d;
  logic        address0_match;                 // Indicates target's address0 matches the one sent by host
  logic        address1_match;                 // Indicates target's address1 matches the one sent by host
  logic        address_match;                  // Indicates one of target's addresses matches the one sent by host
  logic        xact_for_us_q;                  // Target was addressed in this transaction
  logic        xact_for_us_d;                  //     - We only record Stop if the Target was addressed.
  logic        xfer_for_us_q;                  // Target was addressed in this transfer
  logic        xfer_for_us_d;                  //     - event_cmd_complete_o is only for our transfers
  logic [7:0]  input_byte;                     // Register for reads from host
  logic        input_byte_clr;                 // Clear input_byte contents
  logic        acq_fifo_plenty_space;
  logic        acq_fifo_full_or_last_space;
  logic        stretch_addr;
  logic        stretch_rx;
  logic        stretch_tx;
  logic        nack_timeout;
  logic        expect_stop;

  // Target ACK control variables
  logic        can_auto_ack;                   // Whether the FSM may automatically ACK

  // Target bit counter variables
  logic [3:0]  bit_idx;                        // Bit index including ack/nack
  logic        bit_ack;                        // Indicates ACK bit been sent or received
  logic        rw_bit;                         // Indicates host wants to read (1) or write (0)
  logic        host_ack;                       // Indicates host acknowledged transmitted byte


  // Clock counter implementation
  typedef enum logic [1:0] {
    T_SETUP_DATA,
    T_HOLD_DATA,
    T_NO_DELAY
  } tcount_sel_e;

  tcount_sel_e tcount_sel;

  always_comb begin : counter_functions
    tcount_d = tcount_q;
    if (load_tcount) begin
      unique case (tcount_sel)
        T_SETUP_DATA  : tcount_d = 13'(t_r_i) + 13'(tsu_dat_i);
        T_HOLD_DATA   : tcount_d = 14'(thd_dat_i);
        T_NO_DELAY    : tcount_d = 14'h0001;
        default       : tcount_d = 14'h0001;
      endcase
    end else if (target_enable_i) begin
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

  // Keep track of how long the target has been stretching. This is used to
  // timeout and send a NACK instead.
  always_ff @(posedge clk_i or negedge rst_ni) begin : clk_nack_after_stretch
    if (~rst_ni) begin
      stretch_active_cnt <= '0;
    end else if (actively_stretching) begin
      stretch_active_cnt <= stretch_active_cnt + 1'b1;
    end else if (start_detect_i && target_idle_o) begin
      stretch_active_cnt <= '0;
    end
  end

  assign can_auto_ack = !ack_ctrl_mode_i || auto_ack_cnt_i > '0;
  assign ack_ctrl_stretching_o = ack_ctrl_stretching;
  assign acq_fifo_next_data_o = input_byte;

  // Latch whether this transaction is to be NACK'd.
  always_ff @(posedge clk_i or negedge rst_ni) begin : clk_nack_transaction
    if (~rst_ni) begin
      nack_transaction_q <= 1'b0;
    end else begin
      nack_transaction_q <= nack_transaction_d;
    end
  end

  // SDA and SCL at the previous clock edge
  always_ff @(posedge clk_i or negedge rst_ni) begin : bus_prev
    if (~rst_ni) begin
      scl_i_q <= 1'b1;
    end else begin
      scl_i_q <= scl_i;
    end
  end

  // Track the transaction framing and this target's participation in it.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      restart_det_q <= 1'b0;
      xact_for_us_q <= 1'b0;
      xfer_for_us_q <= 1'b0;
    end else begin
      restart_det_q <= restart_det_d;
      xact_for_us_q <= xact_for_us_d;
      xfer_for_us_q <= xfer_for_us_d;
    end
  end

  // Bit counter on the target side
  assign bit_ack = (bit_idx == 4'd8);  // ack

  // Increment counter on negative SCL edge
  always_ff @(posedge clk_i or negedge rst_ni) begin : tgt_bit_counter
    if (~rst_ni) begin
      bit_idx <= 4'd0;
    end else if (start_detect_i) begin
      bit_idx <= 4'd0;
    end else if (scl_i_q && !scl_i) begin
      // input byte clear is always asserted on a "start"
      // condition.
      if (input_byte_clr || bit_ack) begin
        bit_idx <= 4'd0;
      end else begin
        bit_idx <= bit_idx + 1'b1;
      end
    end else begin
      bit_idx <= bit_idx;
    end
  end

  // Deserializer for a byte read from the bus on the target side
  assign address0_match = ((input_byte[7:1] & target_mask0_i) == target_address0_i) &&
                            (target_mask0_i != '0);
  assign address1_match = ((input_byte[7:1] & target_mask1_i) == target_address1_i) &&
                            (target_mask1_i != '0);
  assign address_match = (address0_match || address1_match);

  // Shift data in on positive SCL edge
  always_ff @(posedge clk_i or negedge rst_ni) begin : tgt_input_register
    if (~rst_ni) begin
      input_byte <= 8'h0;
    end else if (input_byte_clr) begin
      input_byte <= 8'h0;
    end else if (!scl_i_q && scl_i) begin
      if (!bit_ack) begin
        input_byte[7:0] <= {input_byte[6:0], sda_i};  // MSB goes in first
      end
    end
  end

  // Detection by the target of ACK bit sent by the host
  always_ff @(posedge clk_i or negedge rst_ni) begin : host_ack_register
    if (~rst_ni) begin
      host_ack <= 1'b0;
    end else if (!scl_i_q && scl_i) begin
      if (bit_ack) begin
        host_ack <= ~sda_i;
      end
    end
  end

  // An artificial acq_fifo_wready is used here to ensure we always have
  // space to absorb a stop / repeat start format byte.  Without guaranteeing
  // space for this entry, the target module would need to stretch the
  // repeat start / stop indication.  If a system does not support stretching,
  // there's no good way for a stop to be NACK'd.
  // Besides the space necessary for the stop format byte, we also need one
  // space to send a NACK. This means that we can notify software that a NACK
  // has happened while still keeping space for a subsequent stop or repeated
  // start.
  logic [TARGET_RX_FIFO_DEPTH_WIDTH-1:0] acq_fifo_remainder;
  assign acq_fifo_remainder = TARGET_RX_FIFO_DEPTH - acq_fifo_depth_i;
  // This is used for acq_fifo_full_o to send the ACQ FIFO full alert to
  // software.
  assign acq_fifo_plenty_space = acq_fifo_remainder > TARGET_RX_FIFO_DEPTH_WIDTH'(2);
  assign acq_fifo_full_or_last_space = acq_fifo_remainder <= TARGET_RX_FIFO_DEPTH_WIDTH'(1);

  // State definitions
  typedef enum logic [4:0] {
    IDLE,
    /////////////////////////
    // Target function states
    /////////////////////////

    // Target function receives start and address from external host
    ACQUIRE_START,
    ADDR_READ,
    // Target function acknowledges the address and returns an ack to external host
    ADDR_ACK_WAIT,
    ADDR_ACK_SETUP,
    ADDR_ACK_PULSE,
    ADDR_ACK_HOLD,
    // Target function sends read data to external host-receiver
    TRANSMIT_WAIT,
    TRANSMIT_SETUP,
    TRANSMIT_PULSE,
    TRANSMIT_HOLD,
    // Target function receives ack from external host
    TRANSMIT_ACK,
    TRANSMIT_ACK_PULSE,
    WAIT_FOR_STOP,
    // Target function receives write data from the external host
    ACQUIRE_BYTE,
    // Target function sends ack to external host
    ACQUIRE_ACK_WAIT,
    ACQUIRE_ACK_SETUP,
    ACQUIRE_ACK_PULSE,
    ACQUIRE_ACK_HOLD,
    // Target function clock stretch handling.
    STRETCH_ADDR_ACK,
    STRETCH_ADDR_ACK_SETUP,
    STRETCH_ADDR,
    STRETCH_TX,
    STRETCH_TX_SETUP,
    STRETCH_ACQ_FULL,
    STRETCH_ACQ_SETUP
  } state_e;

  state_e state_q, state_d;

  logic rw_bit_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      rw_bit_q <= '0;
    end else if (bit_ack && address_match) begin
      rw_bit_q <= rw_bit;
    end
  end

  // Reverse the bit order since data should be sent out MSB first
  logic [TARGET_TX_FIFO_WIDTH-1:0] tx_fifo_rdata;
  assign tx_fifo_rdata = {<<1{tx_fifo_rdata_i}};

  // The usage of target_idle_o directly confuses xcelium and leads the
  // the simulator to a combinational loop. While it may be a tool recognized
  // loop, it is not an actual physical loop, since target_idle affects only
  // state_d, which is not used directly by any logic in this module.
  // This is a work around for a known tool limitation.
  logic target_idle;
  assign target_idle = target_idle_o;

  // During a host issued read, a stop was received without first seeing a nack.
  // This may be harmless but is technically illegal behavior, notify software.
  assign event_unexp_stop_o = target_enable_i & xfer_for_us_q & rw_bit_q &
                                stop_detect_i & !expect_stop;

  // Record each transaction that gets NACK'd.
  assign event_target_nack_o = !nack_transaction_q && nack_transaction_d;

  // Outputs for each state
  always_comb begin : state_outputs
    target_idle_o = 1'b1;
    sda_d = 1'b1;
    scl_d = 1'b1;
    transmitting_o = 1'b0;
    tx_fifo_rready_o = 1'b0;
    acq_fifo_wvalid_o = 1'b0;
    acq_fifo_wdata_o = TARGET_RX_FIFO_WIDTH'(0);
    event_address_match_o = 1'b0;
    event_cmd_complete_o = 1'b0;
    rw_bit = rw_bit_q;
    expect_stop = 1'b0;
    restart_det_d = restart_det_q;
    xact_for_us_d = xact_for_us_q;
    xfer_for_us_d = xfer_for_us_q;
    auto_ack_cnt_clr_o = 1'b0;
    auto_ack_cnt_decr_o = 1'b0;
    ack_ctrl_stretching = 1'b0;
    nack_transaction_d = nack_transaction_q;
    actively_stretching = 1'b0;
    event_tx_arbitration_lost_o = 1'b0;
    event_tx_bus_timeout_o = 1'b0;
    event_read_cmd_received_o = 1'b0;

    unique case (state_q)
      // IDLE: initial state, SDA is released (high), SCL is released if the
      // bus is idle. Otherwise, if no STOP condition has been sent yet,
      // continue pulling SCL low in host mode.
      IDLE: begin
        sda_d = 1'b1;
        scl_d = 1'b1;
        restart_det_d = 1'b0;
        xact_for_us_d = 1'b0;
        xfer_for_us_d = 1'b0;
        nack_transaction_d = 1'b0;
      end

      /////////////////
      // TARGET MODE //
      /////////////////

      // ACQUIRE_START: hold for the end of the start condition
      ACQUIRE_START: begin
        target_idle_o = 1'b0;
        xfer_for_us_d = 1'b0;
        auto_ack_cnt_clr_o = 1'b1;
      end
      // ADDR_READ: read and compare target address
      ADDR_READ: begin
        target_idle_o = 1'b0;
        rw_bit = input_byte[0];

        if (bit_ack) begin
          if (address_match) begin
            event_address_match_o = 1'b1;
            xact_for_us_d = 1'b1;
            xfer_for_us_d = 1'b1;
          end
        end
      end
      // ADDR_ACK_WAIT: pause for hold time before acknowledging
      ADDR_ACK_WAIT: begin
        target_idle_o = 1'b0;

        if (scl_i) begin
          // The controller is going too fast. Abandon the transaction.
          // Nothing gets recorded for this case.
          nack_transaction_d = 1'b1;
        end
      end
      // ADDR_ACK_SETUP: target pulls SDA low while SCL is low
      ADDR_ACK_SETUP: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // ADDR_ACK_PULSE: target pulls SDA low while SCL is released
      ADDR_ACK_PULSE: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // ADDR_ACK_HOLD: target pulls SDA low while SCL is pulled low
      ADDR_ACK_HOLD: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;

        // Upon transition to next state, populate the acquisition fifo
        if (tcount_q == 20'd1) begin
          if (nack_transaction_q) begin
            // No need to record anything here. We already recorded the first
            // NACK'd byte in a stretch state or abandoned the transaction in
            // ADDR_ACK_WAIT.
          end else if (!stretch_addr) begin
            // Only write to fifo if stretching conditions are not met
            event_read_cmd_received_o = rw_bit_q;
            // Write Start/Restart to ACQ FIFO if enabled
            if (acq_start_stop_en_i) begin
              acq_fifo_wvalid_o = 1'b1;
              if (restart_det_q) begin
                acq_fifo_wdata_o = {ACQ_RESTART, input_byte};
              end else begin
                acq_fifo_wdata_o = {ACQ_START, input_byte};
              end
            end
          end
        end
      end
      // TRANSMIT_WAIT: Check if data is available prior to transmit
      TRANSMIT_WAIT: begin
        target_idle_o = 1'b0;
      end
      // TRANSMIT_SETUP: target shifts indexed bit onto SDA while SCL is low
      TRANSMIT_SETUP: begin
        target_idle_o = 1'b0;
        sda_d = tx_fifo_rdata[3'(bit_idx)];
        transmitting_o = 1'b1;
      end
      // TRANSMIT_PULSE: target holds indexed bit onto SDA while SCL is released
      TRANSMIT_PULSE: begin
        target_idle_o = 1'b0;

        // Hold value
        sda_d = sda_q;
        transmitting_o = 1'b1;
      end
      // TRANSMIT_HOLD: target holds indexed bit onto SDA while SCL is pulled low, for the hold time
      TRANSMIT_HOLD: begin
        target_idle_o = 1'b0;

        // Hold value
        sda_d = sda_q;
        transmitting_o = 1'b1;
      end
      // TRANSMIT_ACK: target waits for host to ACK transmission
      TRANSMIT_ACK: begin
        target_idle_o = 1'b0;
      end
      TRANSMIT_ACK_PULSE: begin
        target_idle_o = 1'b0;
        if (!scl_i) begin
          // Pop Fifo regardless of ack/nack
          tx_fifo_rready_o = 1'b1;
        end
      end
      // WAIT_FOR_STOP just waiting for host to trigger a stop after nack
      WAIT_FOR_STOP: begin
        target_idle_o = 1'b0;
        expect_stop = 1'b1;
        sda_d = 1'b1;
      end
      // ACQUIRE_BYTE: target acquires a byte
      ACQUIRE_BYTE: begin
        target_idle_o = 1'b0;
      end
      // ACQUIRE_ACK_WAIT: pause before acknowledging
      ACQUIRE_ACK_WAIT: begin
        target_idle_o = 1'b0;
        if (scl_i) begin
          // The controller is going too fast. Abandon the transaction.
          // Nothing is recorded for this case.
          nack_transaction_d = 1'b1;
        end
      end
      // ACQUIRE_ACK_SETUP: target pulls SDA low while SCL is low
      ACQUIRE_ACK_SETUP: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // ACQUIRE_ACK_PULSE: target pulls SDA low while SCL is released
      ACQUIRE_ACK_PULSE: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // ACQUIRE_ACK_HOLD: target pulls SDA low while SCL is pulled low
      ACQUIRE_ACK_HOLD: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;

        if (tcount_q == 20'd1) begin
          auto_ack_cnt_decr_o = 1'b1;
          acq_fifo_wvalid_o = ~stretch_rx;           // assert that acq_fifo has space
          acq_fifo_wdata_o = {ACQ_DATA, input_byte}; // transfer data to acq_fifo
        end
      end
      // STRETCH_ADDR_ACK: target stretches the clock if matching address cannot be
      // deposited yet. (During ACK phase)
      STRETCH_ADDR_ACK: begin
        target_idle_o = 1'b0;
        scl_d = 1'b0;
        actively_stretching = stretch_addr;

        if (nack_timeout) begin
          nack_transaction_d = 1'b1;
          // Record NACK'd Start bytes as long as there is space.
          // The next state is always WAIT_FOR_STOP, so the ACQ FIFO needs to be
          // written here.
          acq_fifo_wvalid_o = !acq_fifo_full_or_last_space;
          acq_fifo_wdata_o = {ACQ_NACK_START, input_byte};
        end
      end
      // STRETCH_ADDR_ACK_SETUP: target pulls SDA low while pulling SCL low for
      // setup time. This is to prepare the setup time after a stretch.
      STRETCH_ADDR_ACK_SETUP: begin
        target_idle_o = 1'b0;
        sda_d = 1'b0;
        scl_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // STRETCH_ADDR: target stretches the clock if matching address cannot be
      // deposited yet.
      STRETCH_ADDR: begin
        target_idle_o = 1'b0;
        scl_d = 1'b0;
        actively_stretching = stretch_addr;

        if (nack_timeout) begin
          nack_transaction_d = 1'b1;
          // Record NACK'd Start bytes as long as there is space.
          // The next state is always WAIT_FOR_STOP, so the ACQ FIFO needs to be
          // written here (only if ACQ_START_STOP_EN is enabled).
          if (acq_start_stop_en_i) begin
            acq_fifo_wvalid_o = !acq_fifo_full_or_last_space;
            acq_fifo_wdata_o = {ACQ_NACK_START, input_byte};
          end
        end else if (!stretch_addr) begin
          // Write Start/Restart to ACQ FIFO if enabled
          if (acq_start_stop_en_i) begin
            acq_fifo_wvalid_o = 1'b1;
            if (restart_det_q) begin
              acq_fifo_wdata_o = {ACQ_RESTART, input_byte};
            end else begin
              acq_fifo_wdata_o = {ACQ_START, input_byte};
            end
          end
        end
      end
      // STRETCH_TX: target stretches the clock when tx_fifo is empty
      STRETCH_TX: begin
        target_idle_o = 1'b0;
        scl_d = 1'b0;
        actively_stretching = stretch_tx;

        if (nack_timeout) begin
          // Only the NackStop will get recorded (later) to provide ACQ FIFO
          // history of the failed transaction. Meanwhile, the NACK timeout
          // will still get reported.
          nack_transaction_d = 1'b1;
        end
      end
      // STRETCH_TX_SETUP: drive the return data
      STRETCH_TX_SETUP: begin
        target_idle_o = 1'b0;
        scl_d = 1'b0;
        sda_d = tx_fifo_rdata[3'(bit_idx)];
        transmitting_o = 1'b1;
      end
      // STRETCH_ACQ_FULL: target stretches the clock when acq_fifo is full
      STRETCH_ACQ_FULL: begin
        target_idle_o = 1'b0;
        scl_d = 1'b0;
        ack_ctrl_stretching = !can_auto_ack;
        actively_stretching = stretch_rx;

        if (nack_timeout || (sw_nack_i && !can_auto_ack)) begin
          nack_transaction_d = 1'b1;
          acq_fifo_wvalid_o = !acq_fifo_full_or_last_space;
          acq_fifo_wdata_o = {ACQ_NACK, input_byte};
        end
      end
      // STRETCH_ACQ_SETUP: Drive the ACK and wait for T_SETUP_DATA before
      // releasing SCL
      STRETCH_ACQ_SETUP: begin
        target_idle_o = 1'b0;
        scl_d = 1'b0;
        sda_d = 1'b0;
        transmitting_o = 1'b1;
      end
      // default
      default: begin
        target_idle_o = 1'b1;
        sda_d = 1'b1;
        scl_d = 1'b1;
        transmitting_o = 1'b0;
        tx_fifo_rready_o = 1'b0;
        acq_fifo_wvalid_o = 1'b0;
        acq_fifo_wdata_o = TARGET_RX_FIFO_WIDTH'(0);
        event_cmd_complete_o = 1'b0;
        restart_det_d = 1'b0;
        xact_for_us_d = 1'b0;
        auto_ack_cnt_clr_o = 1'b1;
        auto_ack_cnt_decr_o = 1'b0;
        ack_ctrl_stretching = 1'b0;
        nack_transaction_d = 1'b0;
        actively_stretching = 1'b0;
      end
    endcase  // unique case (state_q)

    // start / stop override
    if (target_enable_i && (stop_detect_i || bus_timeout_i)) begin
      event_cmd_complete_o = xfer_for_us_q;
      event_tx_bus_timeout_o = bus_timeout_i && rw_bit_q;
      // Write Stop/NackStop to ACQ FIFO if enabled (legacy behavior)
      // Only write if not already writing from state machine
      if (acq_start_stop_en_i && xact_for_us_q && !acq_fifo_wvalid_o) begin
        acq_fifo_wvalid_o = 1'b1;
        if (nack_transaction_q || bus_timeout_i) begin
          acq_fifo_wdata_o = {ACQ_NACK_STOP, input_byte};
        end else begin
          acq_fifo_wdata_o = {ACQ_STOP, input_byte};
        end
      end
    end else if (target_enable_i && start_detect_i) begin
      restart_det_d = !target_idle_o;
      event_cmd_complete_o = xfer_for_us_q;
    end else if (arbitration_lost_i) begin
      nack_transaction_d = 1'b1;
      event_cmd_complete_o = xfer_for_us_q;
      event_tx_arbitration_lost_o = rw_bit_q;
    end
  end


  assign stretch_rx   = !acq_fifo_plenty_space || !can_auto_ack;
  assign stretch_addr = !acq_fifo_plenty_space;

  // This condition determines whether this target has stretched beyond the
  // timeout in which case it must now send a NACK to the host.
  assign nack_timeout = nack_timeout_en_i && stretch_active_cnt >= nack_timeout_i;

  // Stretch Tx phase when:
  // 1. When there is no data to return to host
  // 2. When the acq_fifo contains any entry other than a singular start condition
  //    read command.
  // 3. When there are unhandled events set in the TX_EVENTS CSR. This is
  //    a synchronization point with software, which needs to clear them
  //    first.
  //
  // Besides the unhandled events, only the fifo depth is checked here, because
  // stretch_tx is only evaluated by the fsm on the read path. This means a read
  // start byte has already been deposited, and there is no need for checking
  // the value of the current state for this signal.
  assign stretch_tx = !tx_fifo_rvalid_i || unhandled_tx_stretch_event_i ||
                        (acq_fifo_depth_i > TARGET_RX_FIFO_DEPTH_WIDTH'(1'b1));

  // Only used for assertion
  logic unused_acq_rdata;
  assign unused_acq_rdata = |acq_fifo_rdata_i;

  // Conditional state transition
  always_comb begin : state_functions
    state_d = state_q;
    load_tcount = 1'b0;
    tcount_sel = T_NO_DELAY;
    input_byte_clr = 1'b0;
    event_tx_stretch_o = 1'b0;

    unique case (state_q)
      // IDLE: initial state, SDA and SCL are released (high)
      IDLE: begin
        // The bus is idle. Waiting for a Start.
      end

      /////////////////
      // TARGET MODE //
      /////////////////

      // ACQUIRE_START: hold for the end of the start condition
      ACQUIRE_START: begin
        if (!scl_i) begin
          state_d = ADDR_READ;
          input_byte_clr = 1'b1;
        end
      end
      // ADDR_READ: read and compare target address
      ADDR_READ: begin
        // bit_ack goes high the cycle after scl_i goes low, after the 8th bit
        // was captured.
        if (bit_ack) begin
          if (address_match) begin
            state_d = ADDR_ACK_WAIT;
            // Wait for hold time to avoid interfering with the controller.
            load_tcount = 1'b1;
            tcount_sel = T_HOLD_DATA;
          end else begin  // !address_match
            // This means this transfer is not meant for us.
            state_d = WAIT_FOR_STOP;
          end
        end
      end
      // ADDR_ACK_WAIT: pause for hold time before acknowledging
      ADDR_ACK_WAIT: begin
        if (scl_i) begin
          // The controller is going too fast. Abandon the transaction.
          state_d = WAIT_FOR_STOP;
        end else if (tcount_q == 20'd1) begin
          if (!nack_addr_after_timeout_i) begin
            // Always ACK addresses in this mode.
            state_d = ADDR_ACK_SETUP;
          end else begin
            if (nack_transaction_q) begin
              // We must have stretched before, and software has been notified
              // through an ACQ FIFO full event. For writes we should NACK all
              // bytes in the transfer unconditionally. For reads, we NACK
              // the address byte, then release SDA for the rest of the
              // transfer.
              // Essentially, we're waiting for the end of the transaction.
              state_d = WAIT_FOR_STOP;
            end else if (stretch_addr) begin
              // Not enough bytes to capture the Start/address byte, but might
              // need to NACK.
              state_d = STRETCH_ADDR_ACK;
            end else begin
              // The transaction hasn't already been NACK'd, and there is
              // room in the ACQ FIFO. Proceed.
              state_d = ADDR_ACK_SETUP;
            end
          end
        end
      end
      // ADDR_ACK_SETUP: target pulls SDA low while SCL is low
      ADDR_ACK_SETUP: begin
        if (scl_i) begin
          state_d = ADDR_ACK_PULSE;
        end
      end
      // ADDR_ACK_PULSE: target pulls SDA low while SCL is released
      ADDR_ACK_PULSE: begin
        if (!scl_i) begin
          state_d = ADDR_ACK_HOLD;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_DATA;
        end
      end
      // ADDR_ACK_HOLD: target pulls SDA low while SCL is pulled low
      ADDR_ACK_HOLD: begin
        if (tcount_q == 20'd1) begin
          // Stretch when requested by software or when there is insufficient
          // space to hold the start / address format byte.
          // If there is sufficient space, the format byte is written into the acquisition fifo.
          // Don't stretch when we are unconditionally nacking the next byte
          // anyways.
          if (nack_transaction_q) begin
            // If the Target is set to NACK already, release SDA and wait
            // for a Stop. This isn't an ideal response for SMBus reads, since
            // 127 bytes of 0xff will just happen to have a correct PEC. It's
            // best for software to ensure there is always space in the ACQ
            // FIFO.
            state_d = WAIT_FOR_STOP;
          end else if (stretch_addr) begin  // !nack_transaction_q
            // Stretching because there is insufficient space to hold the
            // start / address format byte.
            // We should only reach here with !nack_addr_after_timeout_i, since
            // we had enough space for nack_addr_after_timeout_i already,
            // before issuing the ACK.
            state_d = STRETCH_ADDR;
          end else if (rw_bit_q) begin
            // Not NACKing automatically, not stretching, and it's a read.
            state_d = TRANSMIT_WAIT;
          end else begin
            // Not NACKing automatically, not stretching, and it's a write.
            state_d = ACQUIRE_BYTE;
          end
        end
      end
      // TRANSMIT_WAIT: Evaluate whether there are entries to send first
      TRANSMIT_WAIT: begin
        if (stretch_tx) begin
          state_d = STRETCH_TX;
        end else begin
          state_d = TRANSMIT_SETUP;
        end
      end
      // TRANSMIT_SETUP: target shifts indexed bit onto SDA while SCL is low
      TRANSMIT_SETUP: begin
        if (scl_i) begin
          state_d = TRANSMIT_PULSE;
        end
      end
      // TRANSMIT_PULSE: target shifts indexed bit onto SDA while SCL is released
      TRANSMIT_PULSE: begin
        if (!scl_i) begin
          state_d = TRANSMIT_HOLD;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_DATA;
        end
      end
      // TRANSMIT_HOLD: target shifts indexed bit onto SDA while SCL is pulled low
      TRANSMIT_HOLD: begin
        if (tcount_q == 20'd1) begin
          if (bit_ack) begin
            state_d = TRANSMIT_ACK;
          end else begin
            load_tcount = 1'b1;
            tcount_sel = T_HOLD_DATA;
            state_d = TRANSMIT_SETUP;
          end
        end
      end
      // Wait for clock to become positive.
      TRANSMIT_ACK: begin
        if (scl_i) begin
          state_d = TRANSMIT_ACK_PULSE;
        end
      end
      // TRANSMIT_ACK_PULSE: target waits for host to ACK transmission
      // If a nak is received, that means a stop is incoming.
      TRANSMIT_ACK_PULSE: begin
        if (!scl_i) begin
          // If host acknowledged, that means we must continue
          if (host_ack) begin
            state_d = TRANSMIT_WAIT;
          end else begin
            // If host nak'd then the transaction is about to terminate, go to a wait state
            state_d = WAIT_FOR_STOP;
          end
        end
      end
      // An inert state just waiting for host to issue a stop
      // Cannot cycle back to idle directly as other events depend on the system being
      // non-idle.
      WAIT_FOR_STOP: begin
        state_d = WAIT_FOR_STOP;
      end
      // ACQUIRE_BYTE: target acquires a byte
      ACQUIRE_BYTE: begin
        if (bit_ack) begin
          state_d = ACQUIRE_ACK_WAIT;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_DATA;
        end
      end
      // ACQUIRE_ACK_WAIT: pause for hold time before acknowledging
      ACQUIRE_ACK_WAIT: begin
        if (scl_i) begin
          // The controller is going too fast. Abandon the transaction.
          state_d = WAIT_FOR_STOP;
        end else if (tcount_q == 20'd1) begin
          if (nack_transaction_q) begin
            state_d = WAIT_FOR_STOP;
          end else if (stretch_rx) begin
            // If there is no space for the current entry, stretch clocks and
            // wait for software to make space. Also stretch if ACK Control
            // Mode is enabled and the auto_ack_cnt is exhausted.
            state_d = STRETCH_ACQ_FULL;
          end else begin
            state_d = ACQUIRE_ACK_SETUP;
          end
        end
      end
      // ACQUIRE_ACK_SETUP: target pulls SDA low while SCL is low
      ACQUIRE_ACK_SETUP: begin
        if (scl_i) state_d = ACQUIRE_ACK_PULSE;
      end
      // ACQUIRE_ACK_PULSE: target pulls SDA low while SCL is released
      ACQUIRE_ACK_PULSE: begin
        if (!scl_i) begin
          state_d = ACQUIRE_ACK_HOLD;
          load_tcount = 1'b1;
          tcount_sel = T_HOLD_DATA;
        end
      end
      // ACQUIRE_ACK_HOLD: target pulls SDA low while SCL is pulled low
      ACQUIRE_ACK_HOLD: begin
        if (tcount_q == 20'd1) begin
          state_d = ACQUIRE_BYTE;
        end
      end
      // STRETCH_ADDR_ACK: The address phase can not yet be completed, stretch
      // clock and wait.
      STRETCH_ADDR_ACK: begin
        // When there is space in the FIFO go to the next state.
        // If we hit our nack timeout, we must nack the full transaction.
        if (nack_timeout) begin
          state_d = WAIT_FOR_STOP;
        end else if (!stretch_addr) begin
          state_d = STRETCH_ADDR_ACK_SETUP;
          load_tcount = 1'b1;
          tcount_sel = T_SETUP_DATA;
        end
      end
      // STRETCH_ADDR_ACK_SETUP: target pulls SDA low while pulling SCL low for
      // setup time. This is to prepare the setup time after a stretch.
      STRETCH_ADDR_ACK_SETUP: begin
        if (tcount_q == 20'd1) begin
          state_d = ADDR_ACK_SETUP;
        end
      end
      // STRETCH_ADDR: The address phase can not yet be completed, stretch
      // clock and wait.
      STRETCH_ADDR: begin
        // When there is space in the FIFO go to the next state.
        // If we hit our nack timeout, we must nack the full transaction.
        if (nack_timeout) begin
          state_d = WAIT_FOR_STOP;
        end else if (!stretch_addr) begin
          // When transmitting after an address stretch, we need to assume
          // that it looks like a Tx stretch.  This is because if we try
          // to follow the normal path, the logic will release the clock
          // too early relative to driving the data.  This will cause a
          // setup violation.  This is the same case to needing STRETCH_TX_SETUP.
          state_d = rw_bit_q ? STRETCH_TX : ACQUIRE_BYTE;
        end
      end
      // STRETCH_TX: target stretches the clock when tx conditions are not satisfied.
      STRETCH_TX: begin
        // When in stretch state, always notify software that help is required.
        event_tx_stretch_o = 1'b1;
        if (nack_timeout) begin
          state_d = WAIT_FOR_STOP;
        end else if (!stretch_tx) begin
          // When data becomes available, we must first drive it onto the line
          // for at least the "setup" period.  If we do not, once the clock is released, the
          // pull-up in the system will likely immediately trigger a rising clock
          // edge (since the stretch likely pushed us way beyond the original intended
          // rise).  If we do not artificially create the setup period here, it will
          // likely create a timing violation.
          state_d = STRETCH_TX_SETUP;
          load_tcount = 1'b1;
          tcount_sel = T_SETUP_DATA;

          // When leaving stretch state, de-assert software notification
          event_tx_stretch_o = 1'b0;
        end
      end
      // STRETCH_TX_SETUP: Wait for T_SETUP_DATA before going to transmit
      STRETCH_TX_SETUP: begin
        if (tcount_q == 20'd1) begin
          state_d = TRANSMIT_SETUP;
        end
      end
      // STRETCH_ACQ_FULL: target stretches the clock when acq_fifo is full
      // When space becomes available, move on to prepare to ACK. If we hit
      // our NACK timeout we must continue and unconditionally NACK the next
      // one.
      // If ACK Control Mode is enabled, also stretch if the Auto ACK counter
      // is exhausted. If the conditions for an ACK Control stretch are
      // present, NACK the transaction if directed by SW.
      STRETCH_ACQ_FULL: begin
        if (nack_timeout || (sw_nack_i && !can_auto_ack)) begin
          state_d = WAIT_FOR_STOP;
        end else if (~stretch_rx) begin
          state_d = STRETCH_ACQ_SETUP;
          load_tcount = 1'b1;
          tcount_sel = T_SETUP_DATA;
        end
      end
      // STRETCH_ACQ_SETUP: Drive the ACK and wait for T_SETUP_DATA before
      // releasing SCL
      STRETCH_ACQ_SETUP: begin
        if (tcount_q == 20'd1) begin
          state_d = ACQUIRE_ACK_SETUP;
        end
      end
      // default
      default: begin
        state_d = IDLE;
        load_tcount = 1'b0;
        tcount_sel = T_NO_DELAY;
        input_byte_clr = 1'b0;
        event_tx_stretch_o = 1'b0;
      end
    endcase  // unique case (state_q)

    // When a start is detected, always go to the acquire start state.
    // Differences in repeated start / start handling are done in the
    // other FSM.
    if (!target_idle && !target_enable_i) begin
      // If the target function is currently not idle but target_enable is suddenly dropped,
      // (maybe because the host locked up and we want to cycle back to an initial state),
      // transition immediately.
      // The same treatment is not given to the host mode because it already attempts to
      // gracefully terminate.  If the host cannot gracefully terminate for whatever reason,
      // (the other side is holding SCL low), we may need to forcefully reset the module.
      // ICEBOX(#18004): It may be worth having a force stop condition to force the host back to
      // IDLE in case graceful termination is not possible.
      state_d = IDLE;
    end else if (target_enable_i && start_detect_i) begin
      state_d = ACQUIRE_START;
    end else if (stop_detect_i || bus_timeout_i) begin
      state_d = IDLE;
    end else if (arbitration_lost_i) begin
      state_d = WAIT_FOR_STOP;
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

  // Saved sda output used in certain states.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      sda_q <= 1'b1;
    end else begin
      sda_q <= sda_d;
    end
  end

  assign scl_o = scl_d;
  assign sda_o = sda_d;

  // Fed out for interrupt purposes
  assign acq_fifo_full_o = !acq_fifo_plenty_space;

  // Make sure we never attempt to send a single cycle glitch
  `OCAH_OT_ASSERT(SclOutputGlitch_A, $rose(scl_o) |-> ##1 scl_o)

  // If we are actively transmitting, that must mean that there are no
  // unhandled write commands and if there is a command present it must be
  // a read.
  `OCAH_OT_ASSERT(
      AcqDepthRdCheck_A,
      ((state_q == TRANSMIT_SETUP) && (acq_fifo_depth_i > '0)) |-> (acq_fifo_depth_i == 1) && acq_fifo_rdata_i[0])

  // Check that ACQ FIFO is deep enough to support a stop/rstart as well as
  // a nack when it is full.
  `OCAH_OT_ASSERT(TargetRxFifoDeepEnough_A, TARGET_RX_FIFO_DEPTH > 2)

endmodule
