// SPDX-License-Identifier: Apache-2.0
// Description: Serializes byte from flow_active and transmitts it on the I3C
// bus.

module i3c_controller_fsm
  import controller_pkg::*;
  import i3c_pkg::*;
(
    input logic clk_i,
    input logic rst_ni,

    // Interface to SDA/SCL
    input logic ctrl_scl_i,
    input logic ctrl_sda_i,
    output logic ctrl_scl_o,
    output logic ctrl_sda_o,
    input bus_state_t ctrl_bus_i,
    output logic phy_sel_od_pp_o,

    // Is I2C Transfer
    input logic is_i2c_transfer_i,

    // Timing constants
    input logic [i3c_pkg::TimingWidth-1:0] thigh_i,  // high period of the SCL in clock units in Push-Pull Mode
    input logic [i3c_pkg::TimingWidth-1:0] tlow_i,  // low period of the SCL in clock units in Push-Pull Mode
    input logic [i3c_pkg::TimingWidth-1:0] thigh_od_i,  // high period of the SCL in clock units in Open-Drain Mode
    input logic [i3c_pkg::TimingWidth-1:0] thigh_od_init_i,  // high period of the SCL in clock units in Open-Drain Mode during init procedure
    input logic [i3c_pkg::TimingWidth-1:0] tlow_od_i,  // low period of the SCL in clock units in Open-Drain Mode
    input logic [i3c_pkg::TimingWidth-1:0] t_r_i,  // rise time of both SDA and SCL in clock units
    input logic [i3c_pkg::TimingWidth-1:0] t_f_i,  // fall time of both SDA and SCL in clock units
    input logic [i3c_pkg::TimingWidth-1:0] thd_sta_od_i,  // hold time for START in clock units
    input logic [i3c_pkg::TimingWidth-1:0] thd_rsta_i,  // hold time for repeated START in clock units
    input logic [i3c_pkg::TimingWidth-1:0] tsu_rsta_i,  // setup time for repeated START in clock units
    input logic [i3c_pkg::TimingWidth-1:0] tsu_sto_i,  // setup time for STOP in clock units
    input logic [i3c_pkg::TimingWidth-1:0] t_ds_od_i,  // setup time for SDA during START in clock units
    input logic [i3c_pkg::TimingWidth-1:0] tsu_dat_i,  // data setup time in clock units
    input logic [i3c_pkg::TimingWidth-1:0] thd_dat_i,  // data hold time in clock units
    input logic [i3c_pkg::TimingWidth-1:0] t_buf_i,  // bus free time between STOP and START in clock units
    input logic [i3c_pkg::TimingWidth-1:0] t_bus_idle_i,  // Bus IDLE condition time in clock units
    input logic [i3c_pkg::TimingWidth-1:0] t_bus_available_i,  // Bus AVAILABLE condition time in clock units

    //FMT Interface
    input  logic       fmt_fifo_rvalid_i,
    output logic       fmt_fifo_rready_o,
    output logic       fmt_fifo_rdone_o,
    input  logic [7:0] fmt_byte_i,
    input  logic       fmt_bit_i,                   // T bit
    input  logic       fmt_flag_start_before_i,
    input  logic       fmt_flag_stop_after_i,
    input  logic       fmt_flag_restart_after_i,
    output logic       fmt_receive_nack_o,
    output logic       fmt_sda_arbitration_o,
    // fmt RX signals
    output logic [7:0] fmt_byte_o,
    output logic       fmt_bit_o,                   // T bit
    input  logic       fmt_flag_read_bytes_i,
    // this signal is used for DAA where we continuously have to read 8 bytes (without T bit)
    input  logic       fmt_flag_read_continuous_i,
    output logic       fmt_flag_read_valid_o,
    input  logic       fmt_flag_hdr_exit_i


);
  // State definition
  typedef enum logic [3:0] {
    Idle,
    Start,
    Address,
    BusTX,
    BusRX,
    BusReadContinuous,
    ReStart,
    IBI,
    Stop,
    HDRExit
  } state_e;
  // Declare internal signals
  state_e state_d, state_q;

  logic
      tx_bit_q,
      tx_bit_d,
      rx_done_bit_q,
      rx_done_bit_d,
      wait_for_scl_negedge_d,
      wait_for_scl_negedge_q;

  // Bus SCL flow internal signals
  logic scl_negedge, scl_posedge, scl_stable_low, scl_stable_high;

  logic scl_enable, scl_stall;

  // Start stop generator internal signals
  logic start_before, stop_after_d, stop_after_q, repeated_start_d, repeated_start_q;
  logic start_done, stop_done, repeated_start_done;

  logic start_stop_scl, start_stop_sda;
  logic scl_flow_scl, tx_flow_sda;

  logic start_stop_active;

  logic received_nack_d, received_nack_q;
  assign fmt_receive_nack_o = received_nack_q | received_nack_d;  // instantly update fmt flag

  // Open-Drain vs Push-Pull Mode selection
  logic phy_sel_od_pp_d, phy_sel_od_pp_q, phy_sel_od_pp_real_q, phy_sel_od_pp_real_d;
  assign phy_sel_od_pp_o = phy_sel_od_pp_real_q;

  // IBI Signals
  logic ibi_done;
  logic stop_next_q, stop_next_d;

  // Timing Inputs
  logic [i3c_pkg::TimingWidth-1:0] thigh, tlow;
  logic bus_busy, bus_free, bus_idle, bus_available, bus_rx_req_bit;

  // HDR Exit Generation Signals
  logic hdr_exit_done, is_high_q, is_high_d;
  logic [2:0] hdr_falling_count_q, hdr_falling_count_d;
  logic [i3c_pkg::TimingWidth-1:0] timer_d, timer_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      is_high_q <= 1'b0;
      hdr_falling_count_q <= 3'd0;
      timer_q <= '0;
    end else begin
      is_high_q <= is_high_d;
      hdr_falling_count_q <= hdr_falling_count_d;
      timer_q <= timer_d;
    end
  end



  always_comb begin
    phy_sel_od_pp_d = phy_sel_od_pp_q;
    if (start_done) begin
      phy_sel_od_pp_d = 1'b0;
    end
    if ((phy_sel_od_pp_q == 1'b0) && (state_q != Address)) begin // all I3C transactions except first address after Start are in Push-Pull Mode
      phy_sel_od_pp_d = 1'b1;
    end
    // (OCA) Address and ReStart held in OD mode; replaces the separate Address & bus_rx_req_bit gate
    if ((state_q == Idle) || (state_q == Address) || (state_q == Start) || (state_q == BusRX) || (state_q == BusReadContinuous) || (state_q == IBI) || (state_q == ReStart)) begin
      phy_sel_od_pp_d = 1'b0;
    end
  end

  // (OCA) phy_sel_od_pp should only change when SCL is low to prevent SDA changing
  // while SCL is high. That's why we wait until scl is low to update the
  // phy_sel_od_pp_o signal
  assign phy_sel_od_pp_real_d = scl_stable_low || (start_stop_active && (start_stop_scl == 1'b0)) || (state_q == HDRExit) ? phy_sel_od_pp_d : phy_sel_od_pp_real_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      phy_sel_od_pp_q <= 1'b0;
      phy_sel_od_pp_real_q <= 1'b0;
    end else begin
      phy_sel_od_pp_q <= phy_sel_od_pp_d;
      phy_sel_od_pp_real_q <= phy_sel_od_pp_real_d;
    end
  end

  // (OCA) ACK = SDA went low and stayed low; NACK = never low or floated back up. Sample only while
  // driving SCL low so the target's rising-edge SDA release isn't mistaken for a NACK; 
  // flags hold through the high phase for received_nack to read at bus_rx_done.
  logic ack_seen_low_q, ack_high_after_low_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      ack_seen_low_q <= 1'b0;
      ack_high_after_low_q <= 1'b0;
    end else if ((state_q == Address) & tx_bit_q) begin
      if (~phy_sel_od_pp_o & ~ctrl_scl_o) begin
        if (~ctrl_sda_i) ack_seen_low_q <= 1'b1;
        if (ctrl_sda_i & ack_seen_low_q) ack_high_after_low_q <= 1'b1;
      end
    end else begin
      ack_seen_low_q <= 1'b0;
      ack_high_after_low_q <= 1'b0;
    end
  end
  logic ack_is_nack;
  assign ack_is_nack = ~ack_seen_low_q | ack_high_after_low_q;

  // Bus initialization
  logic bus_init_d, bus_init_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      bus_init_q <= 1'b1;
    end else begin
      bus_init_q <= bus_init_d;
    end
  end

  // TX signals
  logic [7:0] bus_tx_req_value;
  logic
      bus_tx_req_byte,
      bus_tx_req_bit,
      bus_tx_done,
      bus_tx_idle,
      bus_tx_req_err,
      bus_error,
      bus_tx_sel_od_pp,
      bus_tx_release;

  // RX signals
  logic [7:0] bus_rx_data, rx_byte_d, rx_byte_q;
  logic bus_rx_req_bit_d, bus_rx_req_bit_q, bus_rx_req_byte, bus_rx_done, bus_rx_idle, t_bit_done;

  // (OCA) Mark the Address state that was entered from BusReadContinuous, i.e. the ENTDAA Dynamic-Address-assignment (DA-send) phase
  // Per Section 5.1.10.1 the Target is locked in the DAA procedure and cannot issue an IBI, so use this flag to suppress IBI detection
  logic daa_addr_phase_d, daa_addr_phase_q;

  // State Transition
  always_comb begin
    state_d = state_q;
    daa_addr_phase_d = daa_addr_phase_q;
    unique case (state_q)
      Idle: begin
        if (fmt_fifo_rvalid_i & fmt_flag_start_before_i & ~is_i2c_transfer_i & bus_available) begin
          state_d = Start;
        end
      end
      Start: begin
        if (start_done) begin
          state_d = Address;
        end
      end
      Address: begin
        if ((wait_for_scl_negedge_q & scl_negedge) | fmt_receive_nack_o) begin
          if (fmt_receive_nack_o) begin  // wait for SCL to finish cycle before switching state
            state_d = fmt_flag_hdr_exit_i ? HDRExit : (fmt_flag_restart_after_i ? ReStart : Stop);
          end else begin
            state_d = fmt_flag_stop_after_i ? Stop : (fmt_flag_restart_after_i ? ReStart : (fmt_flag_read_continuous_i ? BusReadContinuous : (fmt_flag_read_bytes_i ? BusRX : BusTX)));
          end
          daa_addr_phase_d = 1'b0;  // leaving address state, clear DAA indicator
        end
      end
      BusTX: begin
        if (tx_bit_q & bus_tx_done & fmt_fifo_rvalid_i) begin  // only switch state when we have sent the T bit
          state_d = fmt_flag_stop_after_i ? Stop : (fmt_flag_restart_after_i ? ReStart : BusTX);
        end
      end
      BusRX: begin
        if ((bus_rx_done & fmt_flag_read_bytes_i & bus_rx_req_bit_q) || (t_bit_done)) begin
          state_d = (fmt_flag_stop_after_i | stop_next_q) ? Stop : (fmt_flag_restart_after_i ? ReStart : BusRX);
        end
      end
      BusReadContinuous: begin
        if (bus_rx_done & fmt_flag_read_continuous_i) begin
          state_d = fmt_flag_stop_after_i ? Stop : (fmt_flag_restart_after_i ? ReStart : BusReadContinuous);
        end else if ((bus_rx_done || bus_rx_idle) & ~fmt_flag_read_continuous_i) begin  // this happens during DAA where we should go into address state
          state_d = Address;
          daa_addr_phase_d = 1'b1;  // ENTDAA DA-send: SDA-low is DAA arbitration/ACK, not an IBI in Address state
        end
      end
      ReStart: begin
        if (repeated_start_done & fmt_fifo_rvalid_i) begin
          state_d = Address;
        end
      end
      IBI: begin
        if (bus_tx_done) begin
          state_d = ibi_done ? Stop : BusRX; // either NACK by controller or proceed with reading IBI data
        end
      end
      Stop: begin
        if (stop_done) begin
          state_d = Idle;
        end
      end
      HDRExit: begin
        if (hdr_exit_done) begin
          state_d = Stop;
        end
      end
      default: begin
        state_d = Idle;
      end
    endcase
    if (fmt_sda_arbitration_o) begin
      state_d = IBI;
    end

  end

  // Output Logic
  always_comb begin
    bus_init_d = bus_init_q;
    fmt_bit_o = 1'b0;
    fmt_byte_o = rx_byte_q;
    rx_byte_d = rx_byte_q;
    fmt_fifo_rready_o = 1'b0;
    fmt_fifo_rdone_o = 1'b0;
    fmt_flag_read_valid_o = 1'b0;
    received_nack_d = received_nack_q;
    start_before = 1'b0;
    stop_after_d = 1'b0;
    repeated_start_d = 1'b0;
    ctrl_sda_o = 1'b1;
    ctrl_scl_o = 1'b1;
    tx_bit_d = 1'b0;
    rx_done_bit_d = rx_done_bit_q;
    bus_tx_req_byte = 1'b0;
    bus_tx_req_bit = 1'b0;
    bus_tx_req_value = '0;
    bus_tx_release = 1'b0;
    bus_rx_req_byte = 1'b0;
    bus_rx_req_bit = 1'b0;
    bus_rx_req_bit_d = bus_rx_req_bit_q;
    scl_enable = ~start_stop_active;
    scl_stall = 1'b0;
    ibi_done = 1'b0;
    hdr_exit_done = 1'b0;
    is_high_d = is_high_q;
    hdr_falling_count_d = hdr_falling_count_q;
    timer_d = timer_q;
    stop_next_d = fmt_flag_stop_after_i;
    t_bit_done = 1'b0;
    wait_for_scl_negedge_d = wait_for_scl_negedge_q;
    unique case (state_q)
      Idle: begin
        fmt_fifo_rready_o = 1'b1;
        scl_enable = 1'b0;
        received_nack_d = 1'b0;
      end
      Start: begin
        received_nack_d = 1'b0;
        start_before = 1'b1;
        ctrl_sda_o = start_stop_sda;
        ctrl_scl_o = start_stop_scl;
      end
      Address: begin
        ctrl_sda_o = tx_flow_sda;
        ctrl_scl_o = scl_flow_scl;
        bus_rx_req_bit = 1'b0;

        if (tx_bit_q) begin
          tx_bit_d = 1'b1;
          //bus_tx_req_bit = 1'b1;

          //bus_tx_req_value = {7'b0, 1'b1};
          // Read bus to check for NACK
          bus_rx_req_bit = 1'b1;
          // (OCA) NACK iff the accumulated sense over the ACK window says so (see ack_is_nack)
          received_nack_d = bus_rx_done & ack_is_nack;

          if (bus_rx_done) begin
            tx_bit_d = 1'b0;
            wait_for_scl_negedge_d = received_nack_d ? 1'b0 : 1'b1;
            ctrl_sda_o = 1'b0;
            if (received_nack_d) begin
              fmt_fifo_rdone_o = 1'b1;
              ctrl_sda_o = 1'b1;
            end
          end
        end else if (~wait_for_scl_negedge_q) begin
          bus_tx_req_byte  = 1'b1;
          bus_tx_req_value = fmt_byte_i;
          if (bus_tx_done) begin
            tx_bit_d = 1'b1;
          end
        end
        if (wait_for_scl_negedge_q) begin
          ctrl_sda_o = 1'b0;  // Handoff as per Section 5.1.2.3.1
          if (scl_negedge) begin
            ctrl_sda_o = 1'b1;
            fmt_fifo_rdone_o = 1'b1;
            wait_for_scl_negedge_d = 1'b0;
          end
        end
        bus_rx_req_byte = ~phy_sel_od_pp_o & ~bus_rx_req_bit;  // In OD mode read the addr just in case an IBI happens
        // (OCA) covers any transients when in the Address state and prev transactions was a push pull
        if (tx_bit_d & ~bus_rx_done) begin
          if (phy_sel_od_pp_o)                ctrl_sda_o = 1'b0;  // PP: original guard
          else if (ctrl_scl_o & ~ack_is_nack) ctrl_sda_o = 1'b0;  // OD: ACK confirmed -> hold low thru the high phase so the target's release doesn't float SDA up (STOP glitch)
          else                                ctrl_sda_o = 1'b1;  // OD: release so target drives / we can sense the ACK
        end
      end
      BusTX: begin
        if (bus_init_q) begin
          bus_init_d = 1'b0;  // Clear init flag
        end
        ctrl_sda_o = tx_flow_sda;
        ctrl_scl_o = scl_flow_scl;
        if (tx_bit_q) begin
          tx_bit_d = 1'b1;
          bus_tx_req_bit = 1'b1;
          bus_tx_req_value = {7'b0, fmt_bit_i};
          if (bus_tx_done) begin
            tx_bit_d = 1'b0;
            fmt_fifo_rdone_o = 1'b1;
          end
        end else begin
          bus_tx_req_byte  = 1'b1;
          bus_tx_req_value = fmt_byte_i;
          if (bus_tx_done) begin
            tx_bit_d = 1'b1;
          end
        end
      end
      BusRX: begin
        stop_next_d = stop_next_q;
        t_bit_done  = 1'b0;
        if (bus_init_q) begin
          bus_init_d = 1'b0;  // Clear init flag
        end
        ctrl_scl_o = scl_flow_scl;
        bus_rx_req_byte = fmt_flag_read_bytes_i & ~bus_rx_req_bit_q;
        bus_rx_req_bit = bus_rx_req_bit_q;
        // (OCA) Read end-of-data / abort handshake per MIPI I3C Basic v1.1.1 Section 5.1.2.3.4. 
        // While sampling the T-bit, if the Target is driving it Low to signal end of data, the Controller holds SDA Low through
        // the T-bit's SCL-high phase so the Target sees a clean, controller-confirmed read termination and re-arms its receive path.
        if (bus_rx_req_bit_q & ctrl_scl_o & ~ctrl_sda_i) begin
          ctrl_sda_o = 1'b0;
        end
        if (bus_rx_done & bus_rx_req_bit_q) begin
          bus_rx_req_bit_d = 1'b0;
          bus_rx_req_byte = 1'b1;
          fmt_flag_read_valid_o = 1'b1;  // Signals that fmt_byte_o and fmt_bit_o are valid
          fmt_bit_o = bus_rx_data[0];
          // (OCA) end the read: flag it now (bus_rx_done is at the posedge, SCL high), but only pull
          // SDA low once SCL is low -- pulling it low here would be a falling edge under SCL-high (Sr)
          if (fmt_flag_stop_after_i) begin
            stop_next_d = 1'b1;
            if (~ctrl_scl_o) ctrl_sda_o = 1'b0;
          end
        end else if (bus_rx_done & ~bus_rx_req_bit_q) begin
          fmt_byte_o = bus_rx_data;
          if (stop_next_q) begin
            fmt_flag_read_valid_o = 1'b1;
            if (~ctrl_scl_o) ctrl_sda_o = 1'b0;
          end
          bus_rx_req_bit_d = 1'b1;
          bus_rx_req_byte = 1'b0;
          rx_byte_d = bus_rx_data;
        end
        if (stop_next_q) begin  // pull SDA low for the stop, but only while SCL is low
          if (~ctrl_scl_o) ctrl_sda_o = 1'b0;
          stop_next_d = scl_negedge ? 1'b0 : stop_next_q;
          t_bit_done  = scl_negedge;
        end
      end
      BusReadContinuous: begin
        ctrl_scl_o = scl_flow_scl;
        bus_rx_req_byte = 1'b1;
        bus_rx_req_bit_d = 1'b0;
        if (bus_rx_done) begin
          fmt_flag_read_valid_o = 1'b1;  // Signals that fmt_byte_o is valid
          rx_byte_d = bus_rx_data;
          fmt_byte_o = bus_rx_data;
        end
      end
      ReStart: begin
        received_nack_d = 1'b0;
        repeated_start_d = ~start_stop_active;
        ctrl_sda_o = start_stop_sda;
        ctrl_scl_o = start_stop_active ? start_stop_scl : scl_flow_scl;
        fmt_fifo_rready_o = 1'b1;
      end
      IBI: begin
        ctrl_scl_o = scl_flow_scl;
        if (rx_done_bit_q) begin
          bus_tx_req_bit = 1'b1;
          bus_tx_release = 1'b1;  // release SDA after the ACK so the target drives the data phase
          ctrl_sda_o = tx_flow_sda;
          bus_tx_req_value = {7'b0, fmt_bit_i};
          if (bus_tx_done) begin
            rx_done_bit_d = 1'b0;
          end
        end else begin
          rx_byte_d = bus_rx_data;
          fmt_byte_o = bus_rx_data;
          bus_rx_req_byte = 1'b1;
          if (bus_rx_done) begin
            fmt_flag_read_valid_o = 1'b1;  // Signals that fmt_byte_o is valid
            rx_done_bit_d = 1'b1;
          end
        end
        if (fmt_flag_stop_after_i & bus_tx_done) begin  // Controller NACKed the IBI
          ibi_done = 1'b1;
        end
        fmt_fifo_rdone_o = bus_tx_done;
      end
      Stop: begin
        received_nack_d = 1'b0;
        ctrl_scl_o = scl_flow_scl;
        // (OCA) Only pull SDA low while SCL is low; if entered under SCL-high (e.g. from the BusRX T-bit
        // posedge) leave SDA released so it doesn't fall under SCL-high and look like a START.
        // (OCA) if SDA is ALREADY Low under SCL-high (we entered from the BusRX read-abort
        // hold, which drove the end-of-data T-bit Low, see BusRX Section-5.1.2.3.4 handshake), keep
        // holding it Low instead of releasing, otherwise it will be seen as a premature STOP 
        if (~ctrl_scl_o | ~ctrl_sda_i) ctrl_sda_o = 1'b0;
        if (scl_negedge | scl_stable_low | start_stop_active) begin  // wait for cycle to finish and then stop
          stop_after_d = 1'b1;
          ctrl_sda_o = start_stop_sda;
          ctrl_scl_o = stop_after_q ? start_stop_scl : 1'b0;
          received_nack_d = 1'b0;
        end
      end
      HDRExit: begin
        ctrl_sda_o = 1'b1;
        ctrl_scl_o = 1'b0;
        is_high_d = is_high_q;
        hdr_falling_count_d = hdr_falling_count_q;
        timer_d = timer_q;
        if (hdr_falling_count_q >= 3'd4) begin
          timer_d = timer_q + 1;
          hdr_falling_count_d = hdr_falling_count_q;
          // Set up SCL for STOP
          ctrl_sda_o = 1'b0;
          ctrl_scl_o = 1'b0;
          if (timer_q >= tlow_i) begin  // wait before switching to STOP
            hdr_falling_count_d = 3'd0;
            timer_d = '0;
            hdr_exit_done = 1'b1;  // generate STOP condition
            fmt_fifo_rdone_o = 1'b1; // signal to flow_active that we are done with the HDR Exit pattern
          end
        end else begin
          if (timer_q < tlow_i) begin
            timer_d = timer_q + 1;
            ctrl_sda_o = ~is_high_q;
          end else begin
            ctrl_sda_o = ~is_high_q;
            hdr_falling_count_d = ~is_high_q ? hdr_falling_count_q + 1 : hdr_falling_count_q;
            is_high_d = ~is_high_q;
            timer_d = '0;
          end
        end
      end
      default: begin
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      state_q <= Idle;
      tx_bit_q <= 1'b0;
      wait_for_scl_negedge_q <= 1'b0;
      rx_done_bit_q <= 1'b0;
      received_nack_q <= 1'b0;
      bus_rx_req_bit_q <= 1'b0;
      rx_byte_q <= '0;
      stop_after_q <= 1'b0;
      repeated_start_q <= 1'b0;
      stop_next_q <= 1'b0;
      daa_addr_phase_q <= 1'b0;
    end else begin
      state_q <= state_d;
      tx_bit_q <= tx_bit_d;
      wait_for_scl_negedge_q <= wait_for_scl_negedge_d;
      rx_done_bit_q <= rx_done_bit_d;
      received_nack_q <= received_nack_d;
      bus_rx_req_bit_q <= bus_rx_req_bit_d;
      rx_byte_q <= rx_byte_d;
      stop_after_q <= stop_after_d;
      repeated_start_q <= repeated_start_d;
      stop_next_q <= stop_next_d;
      daa_addr_phase_q <= daa_addr_phase_d;
    end
  end

  // Timing Mux
  always_comb begin
    thigh = thigh_i;
    tlow  = tlow_i;
    if (phy_sel_od_pp_o || (state_q == BusRX)) begin  // I3C Push-Pull Mode
      thigh = thigh_i;
      tlow  = tlow_i;
    end else if (~phy_sel_od_pp_o) begin  // I3C bus initialization timings (See t_HIGH_INIT Table 86 I3C Basic Spec)
      thigh = bus_init_q ? thigh_od_init_i : thigh_od_i;
      tlow  = tlow_od_i;
    end
  end

  // ctrl_bus_i lags the pads, so right after a STOP the stale SDA low reads as a
  // phantom IBI in Idle; only detect there once the filtered SDA has been seen high.
  logic idle_sda_high_seen_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      idle_sda_high_seen_q <= 1'b0;
    end else if (state_q != Idle) begin
      idle_sda_high_seen_q <= 1'b0;
    end else if (ctrl_bus_i.sda.value) begin
      idle_sda_high_seen_q <= 1'b1;
    end
  end

  // SDA Arbitration detection logic
  always_comb begin
    fmt_sda_arbitration_o = 1'b0;
    // Check during arbitrable address phase (not during ACK) and in Idle state.
    // Address must stay a pure level check: a losing bit may never read SDA high.
    if ((((state_q == Address) && ~daa_addr_phase_q) ||
         ((state_q == Idle) && idle_sda_high_seen_q)) &&
        (phy_sel_od_pp_o == 1'b0) && (bus_rx_req_bit == 1'b0)) begin
      if (ctrl_bus_i.scl.stable_high & scl_stable_high) begin
        // (OCA) only count as arbitration lost when external agent pulled SDA line while SCL high
        // -> cannot use XOR as it would misdetect current controller puling sda low
        fmt_sda_arbitration_o = ctrl_sda_o & ~ctrl_bus_i.sda.value;
      end
    end
  end


  // Read Bus

  ctrl_bus_rx_flow i_bus_rx_flow (
      .clk_i,
      .rst_ni,

      // (OCA) strobe capture on the DRIVEN SCL posedge, not the synced ctrl_bus_i.scl.pos_edge
      // Same issue as on the tx side for ACK, the target can release control over SDA on posedge
      // so sampling after posedge detection would sample the wrong value of SDA
      .scl_posedge_i(scl_posedge),
      .scl_stable_high_i(ctrl_bus_i.scl.stable_high),
      .sda_i(ctrl_sda_i),

      .rx_req_bit_i(bus_rx_req_bit),
      .rx_req_byte_i(bus_rx_req_byte),
      .rx_data_o(bus_rx_data),
      .rx_done_o(bus_rx_done),
      .rx_idle_o(bus_rx_idle)
  );

  // (OCA) actual value driven on SDA last cycle; fed back into the TX cell so it
  // holds the true line value (incl. what START/STOP gen drove) while awaiting a
  // negedge, instead of its own stale internal guess
  logic ctrl_sda_last_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) ctrl_sda_last_q <= 1'b1;
    else ctrl_sda_last_q <= ctrl_sda_o;
  end

  // SDA driver
  logic unassigned_bus_sel_od_pp;
  // (OCA) drive bus TX OD/PP select from phy_sel_od_pp_o instead of the hardwired 1'b0
  assign bus_tx_sel_od_pp = phy_sel_od_pp_o;
  ctrl_bus_tx_flow i_bus_tx_flow (
      .clk_i,
      .rst_ni,
      .t_r_i,
      .t_su_dat_i      (tsu_dat_i),
      .t_hd_dat_i      (thd_dat_i),
      .scl_negedge_i   (scl_negedge),
      .scl_posedge_i   (scl_posedge),
      .scl_stable_low_i(scl_stable_low),
      .req_byte_i      (bus_tx_req_byte),
      .req_bit_i       (bus_tx_req_bit),
      .req_value_i     (bus_tx_req_value),
      .bus_tx_done_o   (bus_tx_done),
      .bus_tx_idle_o   (bus_tx_idle),
      .req_error_o     (bus_tx_req_err),
      .bus_error_o     (bus_error),
      .sel_od_pp_i     (bus_tx_sel_od_pp),
      .sel_od_pp_o     (unassigned_bus_sel_od_pp),
      .sda_hold_i      (ctrl_sda_last_q),
      .release_i       (bus_tx_release),
      .sda_o           (tx_flow_sda)
  );

  // SCL driver
  bus_scl_flow i_bus_scl_flow (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      // I3C bus timings
      .thigh_i(thigh),
      .tlow_i(tlow),
      .t_r_i(t_r_i),
      .t_f_i(t_f_i),
      // Output I3C Bus events
      .scl_negedge_o(scl_negedge),
      .scl_posedge_o(scl_posedge),
      .scl_stable_low_o(scl_stable_low),
      .scl_stable_high_o(scl_stable_high),
      // Control signals from controller
      .scl_enable_i(scl_enable),
      .scl_stall_i(scl_stall),
      .scl_o(scl_flow_scl)
  );

  // Generate start(S), stop(P) and repeated start(Sr) condition
  bus_start_stop_gen i_bus_start_stop_gen (
      .clk_i,
      .rst_ni,

      .thd_sta_od_i,
      .tlow_i(tlow),
      .thd_rsta_i,
      .tsu_rsta_i,
      .tsu_sto_i,
      .t_ds_od_i,
      .t_r_i,
      .t_f_i,

      .start_before_i(start_before),
      .stop_after_i(stop_after_q),
      .repeated_start_i(repeated_start_q),

      .start_done_o(start_done),
      .stop_done_o(stop_done),
      .repeated_start_done_o(repeated_start_done),

      .scl_o(start_stop_scl),
      .sda_o(start_stop_sda),

      .active_o(start_stop_active)
  );

  ctrl_bus_timers xbus_timers (
      .clk_i,
      .rst_ni,
      .enable_i         (1'b1),
      .reset_counter_ni (ctrl_bus_i.scl.value & ctrl_bus_i.sda.value),
      .t_bus_free_i     (t_buf_i),
      .t_bus_idle_i     (t_bus_idle_i),
      .t_bus_available_i(t_bus_available_i),
      .bus_busy_o       (bus_busy),
      .bus_free_o       (bus_free),
      .bus_idle_o       (bus_idle),
      .bus_available_o  (bus_available)
  );
endmodule
