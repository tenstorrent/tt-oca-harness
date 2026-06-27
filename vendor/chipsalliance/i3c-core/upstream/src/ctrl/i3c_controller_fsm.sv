// SPDX-License-Identifier: Apache-2.0
//
// I3C Controller FSM
// Handles SCL timing generation for both Open Drain (OD) and Push Pull (PP) modes.
// Both OD and PP modes use CSR timing parameters.
//
// Interface designed to connect directly to flow_active.sv

module i3c_controller_fsm
  import controller_pkg::*;
  import i3c_pkg::*;
  (
    input logic clk_i,
    input logic rst_ni,

    // TODO: potentialty pull write queue fifo signals out so the vendor can instantiate either sram or flop array
    // I3C Bus interface
    // TODO: route ctrl_scl_i from ctrl_scl_o from target
    input  logic ctrl_scl_i,
    /*
     * Note: ctrl_scl_i is a few cycles delayed from ctrl_scl_o.
     * In i3c_phy.sv, the caliptra_prim_flop_2sync module adds 2 clock cycles for metastability protection on the input path:

     Additionally, if t_r_i/t_f_i are non zero (in PP mode these get set to 0)
     , In bus_monitor.sv:52-61, previous-cycle values are stored for edge detection in the edge_detector module:
     *

     TODO / Warning: Also RX_BUF_THLD cannot be set to the max or else bus will abort because it detects rx_queue_full_i

     */
    input  logic ctrl_sda_i,
    output logic ctrl_scl_o,
    output logic ctrl_sda_o,

    // PP mode timing inputs (from CSRs)
    input  logic [19:0] t_r_pp_i,         // Rise time (PP mode, typically 0)
    input  logic [19:0] t_f_pp_i,         // Fall time (PP mode, typically 0)
    input  logic [19:0] thigh_pp_i,       // SCL high period (PP mode)
    input  logic [19:0] tlow_pp_i,        // SCL low period (PP mode)
    input  logic [19:0] tsu_pp_i,         // Data setup time (PP mode)
    input  logic [19:0] thd_pp_i,         // Data hold time (PP mode)
    input  logic [19:0] t_casr_i,         // Controller Abort/Stop time (PP mode)
    input  logic [19:0] t_cbsr_i,         // Controller Bit Start time (PP mode)

    // OD mode timing inputs (from CSRs, same as I2C FSM)
    input  logic [19:0] thigh_i,         // SCL high period
    input  logic [19:0] tlow_i,          // SCL low period
    input  logic [19:0] t_r_i,           // Rise time
    input  logic [19:0] t_f_i,           // Fall time
    input  logic [19:0] thd_sta_i,       // START hold time
    input  logic [19:0] tsu_sta_i,       // START setup time
    input  logic [19:0] tsu_sto_i,       // STOP setup time
    input  logic [19:0] tsu_dat_i,       // Data setup time
    input  logic [19:0] thd_dat_i,       // Data hold time
    input  logic [19:0] t_buf_i,         // Bus free time

    // Control interface
    input  logic host_enable_i,
    output logic host_idle_o,

    // TX interface from flow_active.sv
    input  logic       tx_valid_i,       // Byte ready to send
    input  logic [7:0] tx_data_i,        // Data byte to send
    input  start_stop_e tx_start_stop_i, // Start/Stop/Repeated Start indication
    input  logic       tx_is_addr_i,     // Address byte (open-drain, expects ACK)
    input  logic       tx_use_tbit_i,    // Add T-bit after byte (push-pull I3C mode)
    output logic       tx_ready_o,       // Ready for next byte (1 in Idle and after byte completes)
    output logic       rx_ack_o,         // ACK received (valid when tx_ready_o && tx_is_addr_i was set)
    output logic       rx_ack_valid_o,   // ACK valid pulse (high for 1 cycle when ACK sampled)

    // RX interface to flow_active.sv
    input  logic       rx_req_i,         // Read byte request
    output logic       rx_valid_o,       // Received byte valid (pulses 1 cycle)
    output logic [7:0] rx_data_o,        // Received byte data
    output logic       rx_data_last_o,   // Last byte of data target is sending

    output logic       sel_od_pp_o,      // Select signal for OD vs PP mode (for timing and output control logic

    output logic       ibi_detected_o,
    input  logic       ibi_mode_i,
    input  logic       ibi_address_byte_i,

    input  logic       abort_read_i
  );

  // ============================================================================
  // Timing Counter
  // ============================================================================
  typedef enum logic [3:0] {
    tSetupStart,  // START setup: t_r + tsu_sta (OD) or t_r_pp + t_cbsr (PP)
    tHoldStart,   // START hold:  t_f + thd_sta (OD) or t_f_pp + t_casr (PP)
    tSetupData,   // Data setup:  t_r + tsu_dat (OD) or t_r_pp + tsu_pp (PP)
    tClockLow,    // SCL low:     tlow - thd_dat (OD) or tlow_pp - thd_pp (PP)
    tClockPulse,  // SCL high:    t_r + thigh (OD) or t_r_pp + thigh_pp (PP)
    tHoldBit,     // Bit hold:    t_f + thd_dat (OD) or t_f_pp + thd_pp (PP)
    tSetupStop,   // STOP setup:  t_r + tsu_sto (OD) or t_r_pp + t_casr (PP)
    tHoldStop,    // Bus free:    t_r + t_buf - tsu_sta (OD/PP, uses OD t_buf for both)
    tOneDelay,
    tNoDelay      // Minimal delay
  } tcount_sel_e;

  logic [19:0] tcount_q;
  logic [19:0] tcount_d;
  logic        load_tcount;
  tcount_sel_e tcount_sel;

  logic internal_sel_od_pp;

  always_comb begin : counter_functions
    tcount_d = tcount_q;
    if (load_tcount) begin
      if (internal_sel_od_pp == 1'b0) begin
        // Open Drain mode: use CSR timing parameters
        unique case (tcount_sel)
          tSetupStart: tcount_d = t_r_i + tsu_sta_i;
          tHoldStart:  tcount_d = t_f_i + thd_sta_i;
          tSetupData:  tcount_d = t_r_i + tsu_dat_i;
          tClockLow:   tcount_d = tlow_i - thd_dat_i;
          tClockPulse: tcount_d = t_r_i + thigh_i;
          tHoldBit:    tcount_d = t_f_i + thd_dat_i;
          tSetupStop:  tcount_d = t_r_i + tsu_sto_i;
          tHoldStop:   tcount_d = t_r_i - tsu_sta_i;
          tOneDelay:   tcount_d = 20'd2;
          tNoDelay:    tcount_d = 20'd1;
          default:     tcount_d = 20'd1;
        endcase
      end else begin
        // Push Pull mode: use CSR timing parameters (same pattern as OD)
        unique case (tcount_sel)
          tSetupStart: tcount_d = t_r_pp_i + t_cbsr_i;           // Rise + CBS (like t_r + tsu_sta)
          tHoldStart:  tcount_d = t_f_pp_i + t_casr_i;           // Fall + CAS (like t_f + thd_sta)
          tSetupData:  tcount_d = t_r_pp_i + tsu_pp_i;           // Rise + data setup
          tClockLow:   tcount_d = tlow_pp_i - thd_pp_i;          // Low minus hold
          tClockPulse: tcount_d = t_r_pp_i + thigh_pp_i;         // Rise + high period
          tHoldBit:    tcount_d = t_f_pp_i + thd_pp_i;           // Fall + data hold
          tSetupStop:  tcount_d = t_r_pp_i + t_casr_i;           // Rise + CAS (like t_r + tsu_sto)
          tHoldStop:   tcount_d = t_r_pp_i - t_cbsr_i;           // Rise + bus_free - CBS (uses OD t_buf)
          tOneDelay:   tcount_d = 20'd2;
          tNoDelay:    tcount_d = 20'd1;
          default:     tcount_d = 20'd1;
        endcase
      end
    end else if (host_enable_i && (tcount_q > 20'd1)) begin
      tcount_d = tcount_q - 1'b1;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin : clk_counter
    if (!rst_ni) begin
      tcount_q <= 20'd1;
    end else begin
      tcount_q <= tcount_d;
    end
  end

  // ============================================================================
  // Bit Counter
  // ============================================================================
  // as sf sf sf sf sf before
  // before
  logic [2:0] bit_index;  // 4 bits to count 0-8 (8 data bits + 1 ACK/T-bit)
  logic       bit_decr;
  logic       bit_index_clear;
  logic [7:0] shift_reg;
  logic       shift_data_en;
  logic       load_tx_data;

  always_ff @(posedge clk_i or negedge rst_ni) begin : bit_counter
    if (!rst_ni) begin
      bit_index <= 3'd7;
    end else if (bit_index_clear) begin
      bit_index <= 3'd7;
    end else if (bit_decr) begin
      bit_index <= bit_index - 1'b1;
    end
  end

  // Shift register for TX data
  always_ff @(posedge clk_i or negedge rst_ni) begin : shift_register
    if (!rst_ni) begin
      shift_reg <= 8'h00;
    end else if (load_tx_data) begin
      shift_reg <= tx_data_i;
    end
  end

  // ============================================================================
  // ACK/NACK Detection (TX mode)
  // ============================================================================
  logic ack_sampled;
  logic sample_ack;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ack_sampled <= 1'b1;  // Default to NACK (SDA high)
    end else if (sample_ack) begin
      ack_sampled <= ctrl_sda_i;
    end
  end

  // ============================================================================
  // RX Data Path
  // ============================================================================
  logic [7:0] read_byte;       // Shift register for incoming data (MSB first)
  logic       read_byte_clr;   // Clear at start of new RX byte

  // RX shift register - MSB first
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      read_byte <= 8'h00;
    end else if (read_byte_clr) begin
      read_byte <= 8'h00;
    end else if (shift_data_en) begin
      read_byte <= {read_byte[6:0], ctrl_sda_i};  // Shift in MSB first
    end
  end

  // ============================================================================
  // RX T-bit Handling
  // ============================================================================
  // T-bit=0: target done sending, T-bit=1: target has more data
  logic rx_tbit_q;      // Latched T-bit value from target
  logic sample_tbit;    // Sample T-bit on last cycle of ReadTbitPulse

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rx_tbit_q <= 1'b1;  // Default to "more data"
    end else if (sample_tbit) begin
      rx_tbit_q <= ctrl_sda_i;  // Sample T-bit from target
    end
  end

  // ============================================================================
  // FSM States
  // ============================================================================
  typedef enum logic [4:0] {
    Idle,         // Bus released, waiting for command
    Active,
    FetchTxData,
    SetupStart,   // START: Both lines released high
    HoldStart,    // START: SDA low, SCL high
    ClockStart,   // START: SCL pulled low, prepare for data
    ClockLow,     // TX Data: SCL low, drive data onto SDA
    ClockPulse,   // TX Data: SCL high, data stable
    HoldBit,      // TX Data: SCL low after pulse, prepare next bit
    AckLow,       // TX 9th bit: SCL low, release SDA (for ACK) or drive T-bit
    AckPulse,     // TX 9th bit: SCL high, sample ACK or T-bit stable
    AckHold,      // TX 9th bit: SCL low after ACK/T-bit
    SetupStop,    // STOP: SCL low, SDA low
    RiseStop,     // STOP: SCL high, SDA still low
    HoldStop,     // STOP: Both lines released (STOP complete)
    // RX data bit states (controller releases SDA, target drives)
    ReadClockLow,   // RX Data: SCL low, SDA released
    ReadClockPulse, // RX Data: SCL high, sample SDA at end
    ReadHoldBit,    // RX Data: SCL low after sampling
    // RX 9th bit (T-bit) states - TARGET drives T-bit, controller samples
    // T-bit=0: target done, T-bit=1: target has more data
    ReadTbitLow,    // RX T-bit: SCL low, SDA released (OD mode)
    ReadTbitPulse,  // RX T-bit: SCL high, sample T-bit from target
    ReadTbitHold    // RX T-bit: SCL low, respond based on T-bit value
  } state_e;

  state_e state_q, state_d;

  // Internal control signals
  logic scl_d, sda_d;

  // Track previous cycle's ctrl_sda_o
  logic sda_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) sda_q <= 1'b1;
    else         sda_q <= sda_d;
  end

  // Track previous cycle's ctrl_scl_i for edge detection
  logic ctrl_scl_i_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) ctrl_scl_i_q <= 1'b1;
    else         ctrl_scl_i_q <= ctrl_scl_i;
  end

  // Rising edge detection - used for sampling SDA at the correct time
  // Since ctrl_scl_i and ctrl_sda_i go through the same synchronizer path,
  // ctrl_sda_i is valid when we see ctrl_scl_i rise
  logic scl_i_posedge;
  assign scl_i_posedge = !ctrl_scl_i_q && ctrl_scl_i;

  logic sample_start_stop;

  logic log_start_q, log_start_d;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      log_start_q     <= 1'b0;
    end
    else begin
      log_start_q     <= log_start_d;
    end
  end

  /*
   rx_data_last_o tells flow_active.sv that the target is sending the last
   byte of data to the controller.

   This works by checking the 9th t-bit bit (rx_tbit_q). Normally if the target drives
   this t-bit to 1, this means more data is to be sent.
   If it drives the t-bit to 0, that means it is done sending

   However, for IBI's, the target can send data in the broadcast 8'h7e byte, and instead of the 9th
   bit being a t-bit, it is an ACK that the controller drives to 0 if it accepts the IBI

   (&& !ibi_address_byte_i) solves this: if we are in the broadcast address state where the 9th bit
   is an ack that can be driven 0, rx_data_last_o should not be able to be set to 1
   */
  assign rx_data_last_o = !rx_tbit_q && !ibi_address_byte_i;

  assign ibi_detected_o = (state_q == Idle || (shift_reg == 8'hfc && state_q == ClockPulse)) ? ctrl_sda_o && !ctrl_sda_i : 1'b0;


  // ============================================================================
  // State Outputs
  // ============================================================================
  always_comb begin : state_outputs
    host_idle_o = 1'b0;
    scl_d = 1'b1;
    sda_d = 1'b1;
    rx_ack_o = 1'b0;
    rx_ack_valid_o = 1'b0;
    rx_valid_o = 1'b0;
    rx_data_o = read_byte;

    // 0 = OD mode, 1 = PP mode

    //TODO: ddress Header following a Sr can be in Push-pull. I3C Basic 5.1.2.2.4. For now keeping it in OD

    internal_sel_od_pp = ~tx_is_addr_i && (!ibi_address_byte_i);  // Default: PP for data, OD for address

    unique case (state_q)
      Idle: begin
        sda_d = 1'b1;
        scl_d = rx_req_i ? 1'b0 : 1'b1;
      end

      Active: begin
        // If this is a transaction start, do not drive scl low
        // since in the next state we will drive it high to initiate
        // the start bit.
        // If this is a restart, continue driving the clock low.
        scl_d = tx_start_stop_i == Start ? 1'b1 : 1'b0;
        sda_d = sda_q; // drive sda to previous value to avoid glitches when transitioning states
      end

      SetupStart: begin
        // Both lines released (high) - setup for START
        scl_d = 1'b1;
        sda_d = 1'b1;
      end

      HoldStart: begin
        // SDA goes low while SCL is still high (START condition)
        scl_d = 1'b1;
        sda_d = 1'b0;
      end

      ClockStart: begin
        // SCL goes low, SDA stays low, prepare to drive first data bit
        scl_d = 1'b0;
        sda_d = 1'b0;
      end

      ClockLow: begin
        // SCL low, drive data bit onto SDA
        scl_d = 1'b0;
        // bit_index 8 means we just started, use bit 7 (MSB)
        // bit_index 7-1 are data bits
        // bit_index 0 is handled in AckLow
        if (tx_start_stop_i == RepeatedStart && !log_start_q) begin
          sda_d = 1'b1;
        end
        else begin
          sda_d = shift_reg[bit_index];
        end
      end

      ClockPulse: begin
        // SCL high, keep data stable
        scl_d = 1'b1;
        sda_d = shift_reg[bit_index];
      end

      HoldBit: begin
        // SCL goes low after pulse
        scl_d = 1'b0;
        sda_d = shift_reg[bit_index];
        internal_sel_od_pp = (tcount_q == 20'd1 && state_d == AckLow && tx_is_addr_i) ? 1'b0 : internal_sel_od_pp;  // If Transitioning to Tbit, force to OD
      end

      AckLow: begin
        // SCL low for 9th bit
        scl_d = 1'b0;
        if (tx_is_addr_i) begin
          // Address byte: release SDA for target to ACK, unless we are in ibi_address_byte_i:
          // to accept the IBI, controller has to drive the ACK bit to 0
          sda_d = ibi_address_byte_i ? (abort_read_i ? 1'b1 : 1'b0) : 1'b1;
        end else if (tx_use_tbit_i) begin
          // odd parity bit
          sda_d = !(^shift_reg);  // Negation of XOR of data bits
        end else begin
          sda_d = 1'b1;
        end
      end

      AckPulse: begin
        // SCL high for 9th bit - sample ACK (or Drive Ack if target is sending its IBI target address) or keep T-bit stable
        scl_d = 1'b1;
        if (tx_is_addr_i) begin
          // Address byte: When handling ACK bit, controller drives SDA to 0 starting posedge of scl
          // to accept the IBI, controller has to drive the ACK bit to 0
          // Consult I3C Basic Spec 5.1.2.3.1
          sda_d = ibi_address_byte_i ? (abort_read_i ? 1'b1 : 1'b0) : 1'b0;
        end else if (tx_use_tbit_i) begin
          // odd parity bit
          sda_d = !(^shift_reg);  // Negation of XOR of data bits
        end else begin
          sda_d = 1'b1;
        end
      end

      AckHold: begin
        // SCL low after 9th bit, signal ready for next byte
        scl_d = 1'b0;
        if (tx_is_addr_i) begin
          // For IBI handling, controller needs to let go of sda line at negedge of scl as target will start driving data bits in pp mode
          // Consult I3C Basic Spec 5.1.2.3.1
          sda_d = ibi_address_byte_i ? 1'b1 : 1'b0;
        end else if (tx_use_tbit_i) begin
          // odd parity bit
          sda_d = !(^shift_reg);  // Negation of XOR of data bits
        end else begin
          sda_d = 1'b1;
        end

        // Report ACK/NACK status
        if (tx_is_addr_i) begin
          rx_ack_o = ~ack_sampled;   // ACK = SDA low
          rx_ack_valid_o = 1'b1;
        end

        if(tcount_q == 20'd1 && ibi_address_byte_i) begin
          // Output RX data
          rx_valid_o = 1'b1;
          rx_data_o = read_byte;
        end
      end

      FetchTxData: begin
        // Prepare to drive next byte, keep lines released until ClockLow
        scl_d = 1'b0;
        sda_d = sda_q;  // Keep SDA at previous value to avoid glitches when transitioning between bytes
      end

      SetupStop: begin
        // SCL low, ensure SDA is low
        scl_d = 1'b0;
        sda_d = 1'b0;
      end

      RiseStop: begin
        // SCL high, SDA still low (setup for STOP)
        scl_d = 1'b1;
        sda_d = 1'b0;
      end

      HoldStop: begin
        // Both lines released (STOP condition complete)
        scl_d = 1'b1;
        sda_d = 1'b1;
      end

      // ========================================================================
      // RX Data Bit States - controller releases SDA, target drives
      // ========================================================================
      ReadClockLow: begin
        scl_d = 1'b0;   // SCL low
        sda_d = 1'b1;   // Release SDA (target drives)
      end

      ReadClockPulse: begin
        scl_d = 1'b1;   // SCL high (sampling window)
        sda_d = 1'b1;   // Release SDA
      end

      ReadHoldBit: begin
        scl_d = 1'b0;   // SCL low
        sda_d = 1'b1;   // Release SDA
        internal_sel_od_pp = (tcount_q == 20'd1 && state_d == ReadTbitLow) ? 1'b0 : internal_sel_od_pp;  // If Transitioning to Tbit, force to OD
      end

      // ========================================================================
      // RX T-bit States - TARGET drives T-bit, controller samples (Open Drain)
      // T-bit=0: target done sending, T-bit=1: target has more data
      // ========================================================================
      ReadTbitLow: begin
        scl_d = 1'b0;   // SCL low
        sda_d = ibi_mode_i && ibi_address_byte_i ? 1'b0 : 1'b1;  // Release SDA, unless we are acking an IBI request
        internal_sel_od_pp = 1'b0;  // Open Drain for T-bit

      end

      ReadTbitPulse: begin
        scl_d = 1'b1;   // SCL high, sample T-bit from target

        if (ibi_mode_i && ibi_address_byte_i) begin
          sda_d = 1'b0; // ACK IBI request
        end
        else begin
          if(abort_read_i) begin
            if(tcount_q <= 20'd2) begin // the controller needs to ensure enough delay after SCL rising before driving SDA low: see 5.1.2.3.4
              sda_d = 1'b0; // to trigger a repeated start to end normal read transaction
            end
          end
          else begin
            sda_d = rx_tbit_q;
          end
        end

        internal_sel_od_pp = 1'b0;  // Open Drain
      end

      ReadTbitHold: begin
        scl_d = 1'b0;   // SCL low

        if (ibi_mode_i && ibi_address_byte_i) begin
          sda_d = 1'b1; // Let go of SDA after ACKing IBI request so target can drive data bits in PP mode. See 5.1.2.3.2
        end
        else begin
          sda_d = abort_read_i ? 1'b0 : rx_tbit_q; // if we need to abort the read, override sda line to 0
        end

        internal_sel_od_pp = 1'b0;  // Open Drain

        if(tcount_q == 20'd1) begin
          // Output RX data
          rx_valid_o = 1'b1;
          rx_data_o = read_byte;
        end
      end

      default: begin
        host_idle_o = 1'b1;
        scl_d = 1'b1;
        sda_d = 1'b1;
      end
    endcase
  end

  // ============================================================================
  // State Transitions
  // ============================================================================
  always_comb begin : state_functions
    state_d = state_q;
    load_tcount = 1'b0;
    tcount_sel = tNoDelay;
    bit_decr = 1'b0;
    bit_index_clear = 1'b0;
    shift_data_en = 1'b0;
    load_tx_data = 1'b0;
    sample_ack = 1'b0;
    read_byte_clr = 1'b0;
    sample_tbit = 1'b0;
    tx_ready_o = 1'b0;
    sample_start_stop = 1'b0;
    log_start_d = log_start_q;


    unique case (state_q)
      Idle: begin

        if(ibi_detected_o) begin
          state_d = Active;
          load_tcount = 1'b1;
          tcount_sel = tOneDelay;  // One cycle delay to latch on start_stop signals
          tx_ready_o = 1'b1;
        end
        else if(tx_valid_i && host_enable_i) begin
          state_d = Active;
          load_tcount = 1'b1;
          tcount_sel = tOneDelay;  // One cycle delay to latch on start_stop signals
          tx_ready_o = 1'b1;
          load_tx_data = 1'b1;
          bit_index_clear = 1'b1;
          sample_start_stop = 1'b1;  // Latch command signals at the start of a transaction
        end

      end

      Active: begin
        if (rx_req_i | (ibi_mode_i && !ibi_address_byte_i)) begin
          // Enter RX (read) mode
          read_byte_clr = 1'b1;
          bit_index_clear = 1'b1;
          state_d = ReadClockLow;
          load_tcount = 1'b1;
          tcount_sel = tClockLow;
        end
        else begin

          unique case (tx_start_stop_i)
            Start: begin
              // START requested before byte
              state_d = SetupStart;
              load_tcount = 1'b1;
              tcount_sel = tSetupStart;
            end
            RepeatedStart: begin
              // Repeated Start requested before byte
              state_d = ClockLow; // For repeated start, we can go directly to clocking data (Sr condition is handled by external logic controlling the bus)
              load_tcount = 1'b1;
              tcount_sel = tClockLow;
            end
            default: begin
              // No START/Sr (None or Stop), go directly to data transmission
              state_d = ClockLow;
              load_tcount = 1'b1;
              tcount_sel = tClockLow;
            end
          endcase
        end
      end

      SetupStart: begin
        if (tcount_q == 20'd1) begin
          state_d = HoldStart;
          load_tcount = 1'b1;
          tcount_sel = tHoldStart;
        end
      end

      HoldStart: begin
        if (tcount_q == 20'd1) begin
          state_d = ClockStart;
          load_tcount = 1'b1;
          tcount_sel = tClockLow;  // Use clock low timing
        end
      end

      ClockStart: begin
        if (tcount_q == 20'd1) begin
          // After START, go directly to first data bit
          state_d = ClockLow;
          load_tcount = 1'b1;
          tcount_sel = tClockLow;
        end
      end

      ClockLow: begin
        if (tcount_q == 20'd1) begin
          load_tcount = 1'b1;
          if (tx_start_stop_i == RepeatedStart && !log_start_q) begin
            state_d = SetupStart;
            tcount_sel = tSetupStart;
            log_start_d = 1;  // Log that we've seen a repeated start so that we don't issue another one
          end else begin
            state_d = ClockPulse;
            tcount_sel = tClockPulse;
          end
        end
      end

      ClockPulse: begin
        if (tcount_q == 20'd1) begin
          state_d = HoldBit;
          load_tcount = 1'b1;
          tcount_sel = tHoldBit;
        end

        // For IBI address byte, we are simultaneously sending out 8'h7e and reading data from target
        if (scl_i_posedge && ibi_address_byte_i) begin
          shift_data_en = 1'b1;
        end
      end

      HoldBit: begin
        if (tcount_q == 20'd1) begin
          if (bit_index == 3'd0) begin
            // Last data bit done, go to 9th bit (ACK/T-bit)
            state_d = AckLow;
            load_tcount = 1'b1;
            tcount_sel = tClockLow;
          end else begin
            // More data bits to transfer
            state_d = ClockLow;
            load_tcount = 1'b1;
            tcount_sel = tClockLow;
            bit_decr = 1'b1;
          end
        end
      end

      AckLow: begin
        if (tcount_q == 20'd1) begin
          // Sample ACK right before we pulse SCL high for the ACK bit;
          // Following I3C Basic 5.1.2.3.1
          if (tx_is_addr_i) begin
            sample_ack = 1'b1;
          end

          state_d = AckPulse;
          load_tcount = 1'b1;
          tcount_sel = tClockPulse;
        end
      end

      AckPulse: begin
        // State transition based on timing counter
        if (tcount_q == 20'd1) begin
          state_d = AckHold;
          load_tcount = 1'b1;
          tcount_sel = tHoldBit;
        end
      end

      AckHold: begin
        if (tcount_q == 20'd1) begin
          if (tx_start_stop_i == Stop) begin
            // STOP requested after this byte
            state_d = SetupStop;
            load_tcount = 1'b1;
            tcount_sel = tClockLow;  // Hold SCL low briefly
          end
          else begin
            state_d = FetchTxData;
            load_tcount = 1'b1;
            tcount_sel = tNoDelay;  // No delay, immediately fetch next byte
          end
          tx_ready_o = 1'b1;
        end
      end

      FetchTxData: begin
        if (tx_valid_i) begin
          load_tx_data = 1'b1;
          bit_index_clear = 1'b1;
          state_d = Active;  // Go back to Active to check for next byte's start/stop conditions
          load_tcount = 1'b1;
          tcount_sel = tOneDelay;
          sample_start_stop = 1'b1;  // Latch command signals for next byte
        end
      end

      SetupStop: begin
        if (tcount_q == 20'd1) begin
          state_d = RiseStop;
          load_tcount = 1'b1;
          tcount_sel = tSetupStop;
          log_start_d = 1'b0;
        end
      end

      RiseStop: begin
        if (tcount_q == 20'd1) begin
          state_d = HoldStop;
          load_tcount = 1'b1;
          tcount_sel = tHoldStop;
        end
      end

      HoldStop: begin
        if (tcount_q == 20'd1) begin
          state_d = Idle;
          load_tcount = 1'b1;
          tcount_sel = tNoDelay;
        end
      end

      // ========================================================================
      // RX Data Bit Transitions
      // ========================================================================
      ReadClockLow: begin
        if (tcount_q == 20'd1) begin
          state_d = ReadClockPulse;
          load_tcount = 1'b1;
          tcount_sel = tClockPulse;
        end
      end

      ReadClockPulse: begin
        // Sample SDA on rising edge of ctrl_scl_i (synchronized with sda_i)
        if (scl_i_posedge) begin
          shift_data_en = 1'b1;
        end
        // State transition based on timing counter
        if (tcount_q == 20'd1) begin
          state_d = ReadHoldBit;
          load_tcount = 1'b1;
          tcount_sel = tHoldBit;
        end
      end

      ReadHoldBit: begin
        if (tcount_q == 20'd1) begin
          if (bit_index == 3'd0) begin
            // Last data bit done, go to 9th bit (sample T-bit from target)
            state_d = ReadTbitLow;
            load_tcount = 1'b1;
            tcount_sel = tClockLow;
          end else begin
            // More bits to read
            state_d = ReadClockLow;
            load_tcount = 1'b1;
            tcount_sel = tClockLow;
            bit_decr = 1'b1;
          end
        end
      end

      // ========================================================================
      // RX T-bit Transitions - sample T-bit from TARGET
      // ========================================================================
      ReadTbitLow: begin
        if (tcount_q == 20'd1) begin
          state_d = ReadTbitPulse;
          load_tcount = 1'b1;
          tcount_sel = tClockPulse;
          sample_tbit = 1'b1;  // Sample T-bit from target at the posedge of SCL going high: See I3C Basic Spec 5.1.2.3.4
        end
      end

      ReadTbitPulse: begin
        // State transition based on timing counter
        if (tcount_q == 20'd1) begin
          state_d = ReadTbitHold;
          load_tcount = 1'b1;
          tcount_sel = tHoldBit;
        end
      end

      ReadTbitHold: begin
        if (tcount_q == 20'd1) begin
          if (rx_tbit_q == 1'b1 || ibi_address_byte_i) begin
            // T-bit=1: Target has more data, return to Idle for next byte
            // If byte read is a target address from an IBI, we ack and must read the next byte

            if(tx_valid_i && host_enable_i) begin
              state_d = Active;
              load_tcount = 1'b1;
              tcount_sel = tOneDelay;  // One cycle delay to latch on start_stop signals
              tx_ready_o = 1'b1;
              load_tx_data = 1'b1;
              bit_index_clear = 1'b1;
              sample_start_stop = 1'b1;  // Latch command signals at the start of a transaction
            end

          end else begin
            // T-bit=0: Target is done, issue STOP
            state_d = SetupStop;
            load_tcount = 1'b1;
            tcount_sel = tClockLow;
          end
        end
      end

      default: begin
        state_d = Idle;
      end
    endcase
  end

  // ============================================================================
  // State Register
  // ============================================================================
  always_ff @(posedge clk_i or negedge rst_ni) begin : state_transition
    if (!rst_ni) begin
      state_q <= Idle;
    end else begin
      state_q <= state_d;
    end
  end

  // ============================================================================
  // Output Assignments
  // ============================================================================
  assign ctrl_scl_o = scl_d;
  assign ctrl_sda_o = sda_d;

  // During controller reads, FSM uses PP timing but controller is not driving the sda line
  assign sel_od_pp_o = internal_sel_od_pp && ( (state_q != ReadClockLow) && (state_q != ReadClockPulse) && (state_q != ReadHoldBit) && (state_q != Active) && (state_q != FetchTxData) );

endmodule
