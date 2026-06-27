// SPDX-License-Identifier: Apache-2.0

// TODO: Add support for data byte ordering modes (HC_CONTROL.DATA_BYTE_ORDER_MODE)

module flow_active
  import controller_pkg::*;
  import i3c_pkg::*;
  #(
    parameter int unsigned HciRespDataWidth = 32,
    parameter int unsigned HciCmdDataWidth  = 64,
    parameter int unsigned HciRxDataWidth   = 32,
    parameter int unsigned HciTxDataWidth   = 32,
    parameter int unsigned HciIbiDataWidth  = 32,

    parameter int unsigned HciRespThldWidth = 8,
    parameter int unsigned HciCmdThldWidth  = 8,
    parameter int unsigned HciRxThldWidth   = 3,
    parameter int unsigned HciTxThldWidth   = 3,
    parameter int unsigned HciIbiThldWidth  = 8,

    parameter int unsigned HciRxFifoDepth   = 64,
    parameter int unsigned HciTxFifoDepth   = 64,
    localparam int unsigned HciTxFifoDepthWidth = $clog2(HciTxFifoDepth + 1),
    localparam int unsigned HciRxFifoDepthWidth = $clog2(HciRxFifoDepth + 1)
  ) (
    input logic clk_i,
    input logic rst_ni,

    // HCI queues
    // Command FIFO
    input logic cmd_queue_full_i,
    input logic cmd_queue_empty_i,
    input logic cmd_queue_rvalid_i,
    output logic cmd_queue_rready_o,
    input logic [HciCmdDataWidth-1:0] cmd_queue_rdata_i,
    // RX FIFO
    input logic rx_queue_full_i,
    input logic [HciRxFifoDepthWidth-1:0] rx_queue_depth_i,
    input logic rx_queue_start_thld_trig_i,
    input logic rx_queue_ready_thld_trig_i,
    input logic rx_queue_empty_i,
    output logic rx_queue_wvalid_o,
    input logic rx_queue_wready_i,
    output logic [HciRxDataWidth-1:0] rx_queue_wdata_o,
    // TX FIFO
    input logic tx_queue_full_i,
    input logic [HciTxFifoDepthWidth-1:0] tx_queue_depth_i,
    input logic tx_queue_start_thld_trig_i,
    input logic tx_queue_ready_thld_trig_i,
    input logic tx_queue_empty_i,
    input logic tx_queue_rvalid_i,
    output logic tx_queue_rready_o,
    input logic [HciTxDataWidth-1:0] tx_queue_rdata_i,
    // Response FIFO
    input logic resp_queue_full_i,
    input logic resp_queue_empty_i,
    output logic resp_queue_wvalid_o,
    input logic resp_queue_wready_i,
    output logic [HciRespDataWidth-1:0] resp_queue_wdata_o,

    // In-band Interrupt queue
    input logic ibi_queue_full_i,
    input logic ibi_queue_empty_i,
    output logic ibi_queue_wvalid_o,
    input logic ibi_queue_wready_data_i,    // Ready for data writes (not full)
    output logic [HciIbiDataWidth-1:0] ibi_queue_wdata_o,
    output logic ibi_status_desc_valid_o,  // NEW: distinguishes status descriptor from data

    // DAT <-> Controller interface
    output logic                          dat_read_valid_hw_o,
    output logic [DatAw-1:0] dat_index_hw_o,
    input  logic [                  63:0] dat_rdata_hw_i,

    // DCT <-> Controller interface
    output logic                          dct_write_valid_hw_o,
    output logic                          dct_read_valid_hw_o,
    output logic [DctAw-1:0] dct_index_hw_o,
    output logic [                 127:0] dct_wdata_hw_o,
    input  logic [                 127:0] dct_rdata_hw_i,

    // I2C Controller interface
    output logic host_enable_o,  // enable host functionality

    output logic fmt_fifo_rvalid_o,
    output logic [I2CFifoDepthWidth-1:0] fmt_fifo_depth_o,
    input logic fmt_fifo_rready_i,
    output logic [7:0] fmt_byte_o,
    output logic fmt_flag_start_before_o,
    output logic fmt_flag_stop_after_o,
    output logic fmt_flag_read_bytes_o,
    output logic fmt_flag_read_continue_o,
    output logic fmt_flag_nak_ok_o,
    output logic unhandled_unexp_nak_o,
    output logic unhandled_nak_timeout_o,

    // RX FIFO queue from I2C Controller
    input logic                   rx_fifo_wvalid_i,
    input logic [RxFifoWidth-1:0] rx_fifo_wdata_i,

    // I3C Controller interface
    output logic       i3c_tx_valid_o,       // Byte/bit ready to send
    // change this naming from 'done' to ready signal
    input  logic       i3c_tx_ready_i,        // Byte/bit transfer ready
    output logic [7:0] i3c_tx_byte_o,        // Data byte to send
    output start_stop_e i3c_start_stop_o,   // Start/Stop/Repeated Start indication for current byte
    output logic       i3c_tx_is_addr_o,     // This is address byte (open-drain, expects ACK)
    output logic       i3c_tx_use_tbit_o,    // Add T-bit after byte (push-pull I3C mode)
    input  logic       i3c_rx_ack_i,         // ACK received (valid when i3c_tx_ready_i && i3c_tx_is_addr_o)
    input  logic       i3c_rx_ack_valid_i,   // ACK valid pulse (high for 1 cycle when ACK sampled)

    // I3C RX interface - bytes received from i3c_controller_fsm
    output logic       i3c_rx_req_o,         // Request next byte from I3C Controller FSM (flow control for RX data)
    input  logic       i3c_rx_valid_i,       // Received byte valid from controller FSM
    input  logic [7:0] i3c_rx_byte_i,        // Received byte data
    input  logic       i3c_rx_byte_last_i,   // Last byte of data sent by Target

    // I3C FSM control & status
    input  logic i3c_fsm_en_i,
    output logic i3c_fsm_idle_o,

    input  logic ibi_detected_i,
    output logic ibi_mode_o,
    output logic ibi_address_byte_o,
    output logic abort_read_o,

    // I3C transfer mode (from command descriptor)
    output i3c_trans_mode_e i3c_trans_mode_o,

    // Errors
    output i3c_err_t err
  );

  assign dct_write_valid_hw_o = '0;
  // rx_queue_wvalid_o is now controlled by the I3CDataRead/PushRxData state logic
  assign err = '0;

  // TODO: do we need separate i2c fsm states?
  typedef enum logic [5:0] {
    Idle = 6'd0,
    WaitStartTrig = 6'd1,       // Wait for TX/RX start threshold condition (I3C HCI 6.5.5)
    FetchDAT = 6'd2,
    I2CWriteImmediate = 6'd3,
    // I3CWriteImmediate removed - uses BroadcastAddr -> TargetAddr -> I3CDataWrite
    FetchTxData = 6'd5,
    PushRxData = 6'd6,
    InitI2CWrite = 6'd7,
    InitI2CRead = 6'd8,
    StallWrite = 6'd9,
    StallRead = 6'd10,
    WriteResp = 6'd12,
    I3CAddressAssignment = 6'd13,
    I3CDataWrite = 6'd14,       // DATA PHASE ONLY (also used by ImmediateDataTransfer)
    I3CDataRead = 6'd15,        // DATA PHASE ONLY
    // Shared Address States (used by CCC, private, and immediate transfers)
    BroadcastAddr = 6'd16,      // S/Sr + 0x7E/W
    TargetAddr = 6'd17,         // Sr + Target Addr + RnW
    // CCC-specific States
    CCC_SendCCCCode = 6'd18,    // CCC code + T-bit
    CCC_DefiningByte = 6'd19,    // Optional defining byte + T-bit
    ReadTargetAddr = 6'd20
  } flow_fsm_state_e;



  // BytesBeforeImmData only used by I2CWriteImmediate (legacy I2C path)
  // TODO: Set from HC_CONTROL.IBA_INCLUDE: 1 if IBA is disabled, otherwise 2
  localparam int unsigned BytesBeforeImmData = 1;

  flow_fsm_state_e state, state_next;

  immediate_data_trans_desc_t immediate_cmd_desc;
  regular_trans_desc_t regular_cmd_desc;
  combo_trans_desc_t combo_cmd_desc;
  addr_assign_desc_t addr_cmd_desc;
  internal_control_desc_t internal_cmd_desc;
  logic [63:0] cmd_desc;

  // Values extracted from the Command Descriptor
  cmd_transfer_dir_e cmd_dir;
  i3c_cmd_attr_e cmd_attr;
  logic [4:0] dev_index;
  logic [3:0] cmd_tid;
  logic [15:0] data_length;
  logic imm_use_def_byte;
  logic wroc;
  logic toc;

  // CCC-specific signals
  logic cmd_present;  // Command Present bit - indicates CCC
  logic [7:0] ccc_code;  // CCC code from descriptor
  logic is_direct_ccc;  // 1 = Direct CCC, 0 = Broadcast CCC

  // Generic incremental counter
  logic [31:0] transfer_cnt;
  logic transfer_cnt_en;
  logic transfer_cnt_rst;

  logic [HciCmdDataWidth-1:0] cmd_queue_rdata;
  logic cmd_queue_rvalid;

  // DAT table
  dat_entry_t dat_rdata;
  // Register DAT data to align with dat_read_valid_d timing.
  // Previously only dat_read_valid_hw_o was registered (to dat_read_valid_d),
  // but dat_rdata_hw_i was captured combinationally. This caused incorrect data
  // capture when the FSM transitioned out of FetchDAT while dat_read_valid_d
  // was still high, since dat_index_hw_o would change and dat_rdata_hw_i would
  // reflect the wrong address.
  logic [63:0] dat_rdata_hw_i_reg;
  logic dat_captured, dat_read_valid_d;

  // DCT table
  // TODO: Use DCT typedef struct
  logic [127:0] dct_rdata;
  logic dct_captured, dct_read_valid_d;

  // Values extracted from the DAT entry
  logic i2c_cmd;

  // TX Queue
  logic [HciTxDataWidth-1:0] tx_dword;
  logic pop_tx_fifo;
  logic [7:0] tx_data_byte;  // Selected byte from tx_dword based on transfer_cnt and byte index within word

  // RX Queue - byte accumulator (stitch 8-bit bytes into 32-bit words)
  logic [1:0] rx_byte_cnt_q, rx_byte_cnt_d;      // Which byte position (0-3) in the 32-bit word
  logic [31:0] rx_word_accum_q, rx_word_accum_d; // Accumulate 4 bytes into 32-bit word
  logic rx_data_phase_active;                     // Set by states that are receiving data

  // Response Queue
  i3c_response_desc_t resp_desc;
  i3c_resp_err_status_e resp_err_status_d, resp_err_status_q;

  // IBI Status Descriptor Queue
  i3c_ibi_status_desc_t ibi_stat_desc;
  i3c_ibi_status_type_e ibi_status_type_q, ibi_status_type_d;

  // Bus active state - tracks if bus is currently owned (no STOP issued)
  // Used to determine if next transaction starts with Start or RepeatedStart
  logic bus_active_q, bus_active_d;

  logic ibi_id_en;
  logic [6:0] ibi_id, ibi_id_next; // target address sent during beginning of IBI

  // Constant signal assignments (I2C legacy - unused in I3C flow)
  assign fmt_flag_read_bytes_o = 1'b0;
  assign fmt_flag_read_continue_o = 1'b0;
  assign fmt_flag_nak_ok_o = 1'b0;
  assign unhandled_unexp_nak_o = 1'b0;
  assign unhandled_nak_timeout_o = 1'b0;

  // Assign generic Command Descriptor to command specific structures
  assign immediate_cmd_desc = cmd_desc;
  assign regular_cmd_desc = cmd_desc;
  assign combo_cmd_desc = cmd_desc;
  assign addr_cmd_desc = cmd_desc;
  assign internal_cmd_desc = cmd_desc;

  // Initialize descriptor's reserved field
  assign resp_desc.__rsvd23_16 = '0;

  // always guaranteed to be in the bottom 3 bits of the command descriptor, regardless of the command descriptor type
  assign cmd_attr = i3c_cmd_attr_e'(cmd_desc[2:0]);

  // Extract command fields from descriptor structs based on command attribute type
  // Note: Most fields are at the same bit positions across descriptor types, so the
  // synthesizer will optimize away redundant muxes. Using struct accessors improves
  // readability and future-proofs against spec changes.
  always_comb begin
    unique case (cmd_attr)
      RegularTransfer: begin
        dev_index = regular_cmd_desc.dev_idx;
        cmd_tid = regular_cmd_desc.tid;
        cmd_dir = regular_cmd_desc.rnw ? Read : Write;
        cmd_present = regular_cmd_desc.cp;
        ccc_code = regular_cmd_desc.cmd;
        i3c_trans_mode_o = regular_cmd_desc.mode;
        toc = regular_cmd_desc.toc;
        wroc = regular_cmd_desc.wroc;
      end
      ImmediateDataTransfer: begin
        dev_index = immediate_cmd_desc.dev_idx;
        cmd_tid = immediate_cmd_desc.tid;
        cmd_dir = immediate_cmd_desc.rnw ? Read : Write;
        cmd_present = immediate_cmd_desc.cp;
        ccc_code = immediate_cmd_desc.cmd;
        i3c_trans_mode_o = immediate_cmd_desc.mode;
        toc = immediate_cmd_desc.toc;
        wroc = immediate_cmd_desc.wroc;
      end
      ComboTransfer: begin
        dev_index = combo_cmd_desc.dev_idx;
        cmd_tid = combo_cmd_desc.tid;
        cmd_dir = combo_cmd_desc.rnw ? Read : Write;
        cmd_present = combo_cmd_desc.cp;
        ccc_code = combo_cmd_desc.cmd;
        i3c_trans_mode_o = combo_cmd_desc.mode;
        toc = combo_cmd_desc.toc;
        wroc = combo_cmd_desc.wroc;
      end
      AddressAssignment: begin
        dev_index = addr_cmd_desc.dev_idx;
        cmd_tid = addr_cmd_desc.tid;
        cmd_dir = Write;  // Address assignment is always write
        cmd_present = 1'b1;  // Address assignment always has CCC
        ccc_code = addr_cmd_desc.cmd;
        i3c_trans_mode_o = sdr0;  // Address assignment uses SDR0
        toc = addr_cmd_desc.toc;
        wroc = addr_cmd_desc.wroc;
      end
      InternalControl: begin
        dev_index = '0;  // Internal control doesn't target a device
        cmd_tid = internal_cmd_desc.tid;
        cmd_dir = Write;
        cmd_present = 1'b0;
        ccc_code = '0;
        i3c_trans_mode_o = sdr0;
        toc = 1'b0;  // Internal control has no toc/wroc
        wroc = 1'b0;
      end
      default: begin
        dev_index = '0;
        cmd_tid = '0;
        cmd_dir = Write;
        cmd_present = 1'b0;
        ccc_code = '0;
        i3c_trans_mode_o = sdr0;
        toc = 1'b0;
        wroc = 1'b0;
      end
    endcase
  end

  // Derived signal: Direct CCC if MSB of CCC code is set
  assign is_direct_ccc = ccc_code[7];

  // Assign DAT entry specific signals
  assign i2c_cmd = dat_rdata.device;

  // Assign constants
  // TODO: Add control logic to constant signals
  assign host_enable_o = 1'b1;
  assign fmt_fifo_depth_o = 8'd1;

  logic rx_req_o;
  assign i3c_rx_req_o = rx_req_o;

  // Capture data from DAT/DCT tables
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      dat_read_valid_d <= 1'b0;
      dct_read_valid_d <= 1'b0;
      dat_rdata <= '0;
      dct_rdata <= '0;
      dat_captured <= 1'b0;
      dct_captured <= 1'b0;
    end else begin
      dat_read_valid_d <= dat_read_valid_hw_o;
      dct_read_valid_d <= dct_read_valid_hw_o;
      if (dat_read_valid_d) begin
        dat_rdata <= dat_rdata_hw_i;
        dat_captured <= 1'b1;
      end else begin
        dat_rdata <= dat_rdata;
        dat_captured <= 1'b0;
      end
      if (dct_read_valid_d) begin
        dct_rdata <= dct_rdata_hw_i;
        dct_captured <= 1'b1;
      end else begin
        dct_rdata <= dct_rdata;
        dct_captured <= 1'b0;
      end
    end
  end

  // Capture command FIFO control signals
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      cmd_queue_rvalid <= '0;
      cmd_queue_rdata  <= '0;
    end else begin
      cmd_queue_rvalid <= cmd_queue_rvalid_i;
      cmd_queue_rdata  <= cmd_queue_rdata_i;
    end
  end

  always_comb begin
    // Counter now starts at 0 for data phase (address phases in separate states)
    unique case (transfer_cnt & 32'd3)
      32'd0: tx_data_byte = (cmd_attr == ImmediateDataTransfer) ? immediate_cmd_desc.def_or_data_byte1 : tx_dword[7:0];
      32'd1: tx_data_byte = (cmd_attr == ImmediateDataTransfer) ? immediate_cmd_desc.data_byte2        : tx_dword[15:8];
      32'd2: tx_data_byte = (cmd_attr == ImmediateDataTransfer) ? immediate_cmd_desc.data_byte3        : tx_dword[23:16];
      32'd3: tx_data_byte = (cmd_attr == ImmediateDataTransfer) ? immediate_cmd_desc.data_byte4        : tx_dword[31:24];
    endcase
  end

  // Assign internals based on the command attribute
  always_comb begin
    unique case (cmd_attr)
      ImmediateDataTransfer: begin
        // If DTT is 5-7, it is a CCC with a defining byte. In such case substract 5 from DTT to
        // get an actual transfer data length.
        // Values:
        // - 0: No payload
        // - 1–4: N bytes are valid
        // - 5: Defining Byte + 0
        // - 6: Defining Byte + 1
        // - 7: Defining Byte + 2
        imm_use_def_byte = immediate_cmd_desc.dtt > 4 ? 1'b1 : 1'b0;
        data_length = imm_use_def_byte ? 16'(immediate_cmd_desc.dtt - 5) : 16'(immediate_cmd_desc.dtt);
      end
      AddressAssignment: begin
        // TODO
        imm_use_def_byte = '0;
        data_length = '0;
      end
      ComboTransfer: begin
        imm_use_def_byte = '0;
        data_length = combo_cmd_desc.data_length;
      end
      InternalControl: begin
        // TODO
        imm_use_def_byte = '0;
        data_length = '0;
      end
      RegularTransfer: begin
        imm_use_def_byte = regular_cmd_desc.dbp;
        data_length = regular_cmd_desc.data_length;
      end
      default: begin
        imm_use_def_byte = '0;
        data_length = '0;
      end
    endcase
  end

  // Control internal transfer counter
  // TODO: Consider using decremental counter with different load values
  // See i2c_controller_fsm.sv for reference
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      transfer_cnt <= '0;
    end else begin
      if (transfer_cnt_rst) begin
        transfer_cnt <= '0;  // Always reset to 0 (transfer_cnt_rst_val eliminated)
      end else if (transfer_cnt_en) begin
        transfer_cnt <= transfer_cnt + 1;
      end else begin
        transfer_cnt <= transfer_cnt;
      end
    end
  end

  // Fetch Command Descriptor from the Command Queue
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      cmd_desc <= '0;
    end else begin
      if (cmd_queue_rvalid_i & cmd_queue_rready_o) begin
        cmd_desc <= cmd_queue_rdata_i;
      end else begin
        cmd_desc <= cmd_desc;
      end
    end
  end

  // Capture data from TX Queue
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      tx_dword <= '0;
    end else begin
      if (pop_tx_fifo) begin
        tx_dword <= tx_queue_rdata_i;
      end else begin
        tx_dword <= tx_dword;
      end
    end
  end

  // Catch every error detected during the Controller operation
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      resp_err_status_q <= Success;
    end else begin
      if (i3c_fsm_idle_o) begin
        resp_err_status_q <= Success;  // Clear error when returning to idle
      end else begin
        resp_err_status_q <= resp_err_status_d;  // Latch new error
      end
      // else: maintain current error status
    end
  end

  // Track bus active state (no STOP issued means bus is still owned)
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      bus_active_q <= 1'b0;
    end else begin
      bus_active_q <= bus_active_d;
    end
  end

  // RX byte accumulator - stitch 8-bit bytes into 32-bit words
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      rx_byte_cnt_q <= 2'd0;
      rx_word_accum_q <= 32'd0;
    end else begin
      rx_byte_cnt_q <= rx_byte_cnt_d;
      rx_word_accum_q <= rx_word_accum_d;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      ibi_id <= 1'b0;
    end
    else if (ibi_id_en) begin
      ibi_id <= ibi_id_next;
    end
  end

  logic ibi_completed;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ibi_mode_o <= 1'b0;
    end
    else if (ibi_completed) begin
      ibi_mode_o <= 1'b0;
    end
    else if (ibi_detected_i) begin
      ibi_mode_o <= ibi_detected_i;
    end
  end

  /*TODO: if threshold is set to max FIFO, abort_read will go off

   */
  assign abort_read_o = ((ibi_mode_o && ibi_queue_full_i) || (!ibi_mode_o && rx_queue_full_i));

  logic ibi_transaction_interrupted, ibi_transaction_interrupted_next;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ibi_transaction_interrupted <= 1'b0;
    end
    else begin
      ibi_transaction_interrupted <= ibi_transaction_interrupted_next;
    end
  end

  // Combinational state output update
  always_comb begin
    i3c_fsm_idle_o = 1'b0;
    transfer_cnt_en = 1'b0;
    cmd_queue_rready_o = 1'b0;
    dat_read_valid_hw_o = 1'b0;
    dct_read_valid_hw_o = 1'b0;
    dat_index_hw_o = '0;
    tx_queue_rready_o = 1'b0;
    pop_tx_fifo = 1'b0;
    transfer_cnt_rst = 1'b1;
    fmt_fifo_rvalid_o = 1'b0;
    fmt_flag_start_before_o = 1'b0;
    ibi_queue_wvalid_o = 1'b0;
    ibi_status_desc_valid_o = 1'b0;  // NEW: default to data write
    resp_queue_wvalid_o = 1'b0;
    fmt_flag_stop_after_o = 1'b0;
    fmt_byte_o = '0;
    dct_wdata_hw_o = '0;
    ibi_queue_wdata_o = '0;
    dct_index_hw_o = '0;
    resp_queue_wdata_o = '0;
    resp_desc.err_status = i3c_resp_err_status_e'(0);
    resp_desc.tid = '0;
    resp_desc.data_length = '0;
    ibi_stat_desc = '0;
    i3c_tx_valid_o = 1'b0;
    i3c_tx_byte_o = '0;
    i3c_tx_is_addr_o = 1'b1;
    i3c_tx_use_tbit_o = 1'b0;
    i3c_start_stop_o = None;
    bus_active_d = bus_active_q;  // Default: maintain current state
    // RX accumulator defaults
    rx_data_phase_active = 1'b0;
    rx_byte_cnt_d = rx_byte_cnt_q;
    rx_word_accum_d = rx_word_accum_q;
    rx_queue_wvalid_o = 1'b0;
    rx_queue_wdata_o = '0;
    rx_req_o = ibi_mode_o ? 1'b1 : cmd_dir;
    ibi_id_en = 1'b0;
    ibi_id_next = '0;

    unique case (state)
      // Idle: Wait for command appearance in the Command Queue
      Idle: begin
        i3c_fsm_idle_o = 1'b1;
        // Assert ready to accept commands when FSM is enabled
        if (i3c_fsm_en_i) begin
          cmd_queue_rready_o = 1'b1;
        end
      end

      // WaitStartTrig: Wait for start threshold condition (I3C HCI 6.5.5)
      WaitStartTrig: begin
        // Just wait - all outputs use default values
        // State transition logic in next-state block checks threshold conditions
      end

      // FetchDAT: Fetch DAT entry
      FetchDAT: begin
        // TODO: Optimize DAT read so it takes just 1 cycle
        dat_read_valid_hw_o = 1'b1;
        dat_index_hw_o = DatAw'(dev_index);
      end
      // I2CWriteImmediate: Execute Immediate Transfer to Legacy I2C Device via I2C Controller
      I2CWriteImmediate: begin
        // TODO: Figure out if the transfer should proceed if its DTT is set to `Defining Byte + 0`
        // since in such scenario it sends only a target device address. It might be better to just
        // report an error.
        transfer_cnt_rst = 1'b0;
        transfer_cnt_en = fmt_fifo_rready_i;
        fmt_fifo_rvalid_o = 1'b1;
        fmt_flag_start_before_o = 1'b0;
        fmt_flag_stop_after_o = 1'b0;
        unique case (transfer_cnt)
          // TODO: Add support for broadcast address control before private transfers. This can
          // be realized via HC_CONTROL.I2C_DEV_PRESENT and HC_CONTROL.IBA_INCLUDE register fields.
          // 32'd0: fmt_byte_o = {7'h7e, 1'b0};
          // Target address
          32'd0: fmt_byte_o = {dat_rdata.static_address, 1'b0};
          // Byte 1
          32'd1:
            fmt_byte_o = imm_use_def_byte ? immediate_cmd_desc.data_byte2
              : immediate_cmd_desc.def_or_data_byte1;
          // Byte 2
          32'd2:
            fmt_byte_o = imm_use_def_byte ? immediate_cmd_desc.data_byte3
              : immediate_cmd_desc.data_byte2;
          // Byte 3
          32'd3: fmt_byte_o = immediate_cmd_desc.data_byte3;
          // Byte 4
          32'd4: fmt_byte_o = immediate_cmd_desc.data_byte4;
          default: fmt_byte_o = '0;
        endcase

        // Send start condition before first byte
        if (transfer_cnt == 0) begin
          fmt_flag_start_before_o = 1'b1;
        end
        // Send stop condition after last byte if TOC is set to STOP
        if (transfer_cnt == data_length + (BytesBeforeImmData - 1)) begin
          fmt_flag_stop_after_o = toc;
        end
        // Disable FIFO valid whenever I2C Controller is not ready or an immediate transfer is finished
        if (fmt_fifo_rready_i | (transfer_cnt == data_length + BytesBeforeImmData)) begin
          fmt_fifo_rvalid_o = 1'b0;
        end
      end
      // I3CWriteImmediate removed - now uses BroadcastAddr -> TargetAddr -> I3CDataWrite

      // if transfer count is not 0, and tx_queue is empty put an overflow error
      FetchTxData: begin
        transfer_cnt_rst = 1'b0;
        tx_queue_rready_o = !tx_queue_empty_i;
        pop_tx_fifo = tx_queue_rvalid_i && tx_queue_rready_o;
      end
      PushRxData: begin
        transfer_cnt_rst = 1'b0;
        // AXI-like handshaking: assert valid unconditionally when in state (if not full)
        // Accumulator reset happens in state transition logic when handshake completes

        if(ibi_mode_o) begin
          if (~ibi_queue_full_i) begin
            ibi_queue_wvalid_o = 1'b1;

            unique case (rx_byte_cnt_q)
              2'd0: ibi_queue_wdata_o = rx_word_accum_q; // Full 4-byte word (counter wrapped to 0 after accumulating 4th byte)
              // Partial word - pad with zeros
              2'd1: ibi_queue_wdata_o = {24'd0, rx_word_accum_q[7:0]};
              2'd2: ibi_queue_wdata_o = {16'd0, rx_word_accum_q[15:0]};
              2'd3: ibi_queue_wdata_o = {8'd0, rx_word_accum_q[23:0]};
            endcase

            // Reset accumulator for next word
            rx_byte_cnt_d = 2'd0;
            rx_word_accum_d = 32'd0;
          end
        end
        else begin
          if (~rx_queue_full_i) begin
            rx_queue_wvalid_o = 1'b1;

            unique case (rx_byte_cnt_q)
              2'd0: rx_queue_wdata_o = rx_word_accum_q; // Full 4-byte word (counter wrapped to 0 after accumulating 4th byte)
              // Partial word - pad with zeros
              2'd1: rx_queue_wdata_o = {24'd0, rx_word_accum_q[7:0]};
              2'd2: rx_queue_wdata_o = {16'd0, rx_word_accum_q[15:0]};
              2'd3: rx_queue_wdata_o = {8'd0, rx_word_accum_q[23:0]};
            endcase

            // Reset accumulator for next word
            rx_byte_cnt_d = 2'd0;
            rx_word_accum_d = 32'd0;
          end
        end
      end
      InitI2CWrite: begin
        // TODO
      end
      InitI2CRead: begin
        // TODO
      end
      StallWrite: begin
        // TODO
      end
      StallRead: begin
        // TODO
      end
      // BroadcastAddr: Send broadcast address 0x7E/W with START or Sr
      // Shared by both CCC and private transfers
      BroadcastAddr: begin
        i3c_tx_byte_o = {`I3C_RSVD_ADDR, 1'b0};
        i3c_tx_valid_o = 1'b1;
        i3c_start_stop_o = Start;
        i3c_tx_is_addr_o = 1'b1;  // Open-drain, expects ACK
        rx_req_o = Write;
        bus_active_d = 1'b1;  // Bus is now active
      end

      // TargetAddr: Send target address + RnW with Repeated Start
      // Shared by both CCC direct and private transfers
      TargetAddr: begin
        i3c_tx_byte_o = {dat_rdata.dynamic_address[6:0], cmd_dir};
        i3c_tx_valid_o = 1'b1;
        i3c_start_stop_o = RepeatedStart;
        i3c_tx_is_addr_o = 1'b1;  // Open-drain, expects ACK
        rx_req_o = Write;
      end

      // CCC_SendCCCCode: Send CCC code byte with T-bit
      CCC_SendCCCCode: begin
        i3c_tx_byte_o = ccc_code;
        i3c_tx_valid_o = 1'b1;
        i3c_tx_is_addr_o = 1'b0;
        i3c_tx_use_tbit_o = 1'b1;
        rx_req_o = Write;
      end

      // CCC_DefiningByte: Send optional defining byte with T-bit
      CCC_DefiningByte: begin
        i3c_tx_byte_o = (cmd_attr == ImmediateDataTransfer) ?
          immediate_cmd_desc.def_or_data_byte1 :
          regular_cmd_desc.dbp;
        i3c_tx_valid_o = 1'b1;
        i3c_tx_is_addr_o = 1'b0;
        i3c_tx_use_tbit_o = 1'b1;
      end

      // I3CAddressAssignment: Address Assignment CCC (SETDASA, ENTDAA)
      // Broadcast addr and CCC code handled by BroadcastAddr/CCC_SendCCCCode
      // This state handles: Sr -> StaticAddr/W -> DynAddr -> P
      I3CAddressAssignment: begin
        transfer_cnt_rst = 1'b0;
        i3c_tx_valid_o = 1'b1;

        unique case (transfer_cnt)
          32'd0: begin
            // Send Repeated Start + Static Address + W
            i3c_tx_byte_o = {dat_rdata.static_address, 1'b0};
            i3c_start_stop_o = RepeatedStart;
            i3c_tx_is_addr_o = 1'b1;  // Open-drain, expects ACK
            transfer_cnt_en = i3c_tx_ready_i && i3c_rx_ack_valid_i;
          end
          32'd1: begin
            // Send Dynamic Address + T-bit, then STOP
            // dat_rdata.dynamic_address[7] is 0, can be used to add parity bit but this is not computed from software. See I3C HCI Spec 8.1.2 for details.
            i3c_tx_byte_o = {dat_rdata.dynamic_address[6:0], 1'b0};
            i3c_tx_is_addr_o = 1'b0;
            i3c_tx_use_tbit_o = 1'b1;
            i3c_start_stop_o = Stop;
            transfer_cnt_en = i3c_tx_ready_i;
            bus_active_d = 1'b0;  // Bus released
          end
          default: begin
            // Should not reach here
            i3c_tx_byte_o = '0;
          end
        endcase
      end
      // I3CDataWrite: Data phase only - send bytes from TX queue or descriptor
      // Address phases handled by BroadcastAddr and TargetAddr states
      I3CDataWrite: begin
        transfer_cnt_rst = 1'b0;
        transfer_cnt_en = i3c_tx_ready_i;
        i3c_tx_valid_o = 1'b1;
        i3c_tx_byte_o = tx_data_byte;  // Counter starts at 0 for data phase
        i3c_tx_use_tbit_o = 1'b1;  // Push-pull mode with T-bit
        i3c_tx_is_addr_o = 1'b0;

        if(resp_err_status_q == Ovl) begin
          i3c_start_stop_o = Stop;
          bus_active_d = 1'b0;  // Bus released
        end
        else if (transfer_cnt == data_length - 32'd1) begin // STOP after last data byte if TOC is set
          if (toc) begin
            i3c_start_stop_o = Stop;
            bus_active_d = 1'b0;  // Bus released
          end
          else begin
            i3c_start_stop_o = RepeatedStart;
          end
        end
      end
      // I3CDataRead: Data phase only - receive bytes from target
      // Address phases handled by BroadcastAddr and TargetAddr states
      I3CDataRead: begin
        i3c_tx_valid_o = 1'b1;
        i3c_tx_byte_o = 8'h00;  // Dummy byte, data is actually received from i3c_rx_byte_i
        i3c_tx_is_addr_o = 1'b0;
        transfer_cnt_rst = 1'b0;
        transfer_cnt_en = i3c_rx_valid_i;  // Increment counter on pos edge of i3c_rx_valid_i to count received bytes

        rx_data_phase_active = 1'b1;  // Enable shared RX accumulation
      end
      // WriteResp: Handling Response Descriptor and IBI status descriptor
      WriteResp: begin
        resp_desc.err_status = resp_err_status_q;
        resp_desc.tid = cmd_tid;
        // For writes, we return remaining data length, for reads we return recieved data length (I3C HCI 8.5)
        resp_desc.data_length = cmd_dir == Write ? data_length - transfer_cnt : transfer_cnt;

        ibi_stat_desc.last_status = i3c_rx_byte_last_i;
        // first byte sent by Target is it's addr, so subtract by 1
        ibi_stat_desc.data_length = transfer_cnt;
        ibi_stat_desc.ibi_id = ibi_id;
        ibi_stat_desc.error = (resp_err_status_q != Success);

        // AXI-like handshaking: assert valid unconditionally when in state
        // write to IBI queue, not response queue
        if(ibi_mode_o) begin
          ibi_queue_wvalid_o = 1'b1;
          ibi_queue_wdata_o = ibi_stat_desc;
          ibi_status_desc_valid_o = 1'b1;  // NEW: indicate this is a status descriptor
        end
        else begin
          resp_queue_wvalid_o = 1'b1;  // Assert valid unconditionally (no ready check)
          resp_queue_wdata_o  = resp_desc;
        end
      end

      ReadTargetAddr: begin
        i3c_tx_valid_o = 1'b1;
        i3c_tx_byte_o = 8'h00;  // Dummy byte, data is actually received from i3c_rx_byte_i
        i3c_tx_is_addr_o = 1'b1;

        if (i3c_rx_valid_i) begin
          ibi_id_next = i3c_rx_byte_i[7:1];
          ibi_id_en = 1'b1;
        end
      end

      default: begin
        resp_desc.err_status = i3c_resp_err_status_e'(0);
        resp_desc.tid = '0;
        resp_desc.data_length = '0;
      end
    endcase

    // Shared RX byte accumulation logic - ONLY accumulates, PushRxData handles pushing
    if (rx_data_phase_active && i3c_rx_valid_i) begin
      // Shift byte into accumulator based on byte position
      unique case (rx_byte_cnt_q)
        2'd0: rx_word_accum_d[7:0]   = i3c_rx_byte_i;
        2'd1: rx_word_accum_d[15:8]  = i3c_rx_byte_i;
        2'd2: rx_word_accum_d[23:16] = i3c_rx_byte_i;
        2'd3: rx_word_accum_d[31:24] = i3c_rx_byte_i;
      endcase
      // Increment byte counter (wraps 0->1->2->3->0)
      rx_byte_cnt_d = rx_byte_cnt_q + 2'd1;
    end
  end

  // Combinational state transition
  always_comb begin
    state_next = state;
    ibi_completed = 1'b0;
    ibi_transaction_interrupted_next = ibi_transaction_interrupted;
    resp_err_status_d = resp_err_status_q;  // Default: no error
    ibi_address_byte_o = 1'b0;

    unique case (state)
      // Idle: Wait for command appearance in the Command Queue
      Idle: begin
        if (i3c_fsm_en_i) begin
          if (ibi_mode_o) begin
            state_next = ReadTargetAddr;
            ibi_address_byte_o = 1'b1;
          end
          else if(~cmd_queue_empty_i & cmd_queue_rvalid_i) begin
            state_next = WaitStartTrig;  // Check start threshold before proceeding
          end
        end
      end
      // WaitStartTrig: Wait for TX/RX start threshold condition (I3C HCI 6.5.5)
      WaitStartTrig: begin
        // I3C HCI 6.5.5: For Write transfers, wait until TX queue has enough data
        // (threshold met OR transfer short enough to fit in current queue depth).
        // For Read transfers, wait until RX queue has enough space.
        // For Immediate Data Transfer, bypass the check (data is in descriptor).
        if ((cmd_dir == Write && cmd_attr != ImmediateDataTransfer &&
              (tx_queue_start_thld_trig_i || (data_length <= (tx_queue_depth_i << 2)))) ||
            (cmd_attr == ImmediateDataTransfer) ||
            (cmd_dir == Read && rx_queue_start_thld_trig_i)) begin
          state_next = FetchDAT;
        end
      end
      // FetchDAT: Fetch DAT entry
      // All I3C commands go through BroadcastAddr (CCC, private, immediate, address assignment)
      FetchDAT: begin
        if (dat_captured) begin
          state_next = BroadcastAddr;
        end
      end
      // I2CWriteImmediate: Execute Immediate Transfer to Legacy I2C Device via I2C Controller
      I2CWriteImmediate: begin
        if (transfer_cnt == data_length + BytesBeforeImmData) begin
          state_next = wroc ? WriteResp : Idle;
        end
      end
      // I3CWriteImmediate removed - now uses BroadcastAddr -> TargetAddr -> I3CDataWrite
      FetchTxData: begin

        if(transfer_cnt != '0 && tx_queue_empty_i) begin // we allow for the tx queue to be empty for the first byte, but not following bytes
          state_next = I3CDataWrite;
          resp_err_status_d = Ovl;
        end
        else if (pop_tx_fifo) begin
          if (~i2c_cmd) begin
            // Same for both CCC and private transfers - address phases already handled
            state_next = I3CDataWrite;
          end else begin
            state_next = InitI2CWrite;
          end
        end
      end
      PushRxData: begin
        // AXI-like: Only transition when handshake completes (valid & ready)
        // Reset accumulator only after successful transfer

        if(ibi_mode_o) begin
          // Wait for handshake to complete before transitioning
          if (ibi_queue_wvalid_o & ibi_queue_wready_data_i) begin
            // // Reset accumulator after successful transfer
            // rx_byte_cnt_d = 2'd0;
            // rx_word_accum_d = 32'd0;

            // if we are handling an IBI, the IBI status descriptor can only push 255 bytes at a time
            state_next = (i3c_rx_byte_last_i || transfer_cnt[7:0] == 8'd255) ? WriteResp : I3CDataRead;
          end
        end
        else begin // normal data read
          // Wait for handshake to complete before transitioning
          if (rx_queue_wvalid_o & rx_queue_wready_i) begin
            // // Reset accumulator after successful transfer
            // rx_byte_cnt_d = 2'd0;
            // rx_word_accum_d = 32'd0;

            if (i3c_rx_byte_last_i) begin
              state_next = wroc ? WriteResp : Idle;
            end
            else begin
              // More data to receive
              if (~i2c_cmd) begin
                // Same for both CCC and private - address phases already handled
                state_next = I3CDataRead;
              end else begin
                state_next = InitI2CRead;
              end
            end
          end
        end
      end
      InitI2CWrite: begin
        // TODO
      end
      InitI2CRead: begin
        // TODO
      end
      StallWrite: begin
        // TODO
      end
      StallRead: begin
        // TODO
      end

      // BroadcastAddr: Send 0x7E/W, then branch based on if there is a CCC command to send
      BroadcastAddr: begin
        // Target can send IBI during Broadcast 0x7E
        // ignore IBI if IBI queue is full
        if(ibi_detected_i) begin
          state_next = ReadTargetAddr;
          ibi_address_byte_o = 1'b1;
          ibi_transaction_interrupted_next = 1'b1;
        end
        else if (i3c_rx_ack_valid_i && i3c_tx_ready_i) begin
          if (!i3c_rx_ack_i) begin
            // NACK received on broadcast address - abort transfer
            state_next = WriteResp;
            resp_err_status_d = AddrHeader;
          end
          else if (cmd_present) begin
            state_next = CCC_SendCCCCode;  // CCC path
          end
          else begin
            state_next = TargetAddr;        // Private transfer path
          end
        end
      end

      // TargetAddr: Send target address, then go to data phase
      TargetAddr: begin
        if(i3c_rx_ack_valid_i && i3c_tx_ready_i) begin
          if (!i3c_rx_ack_i) begin
            // NACK received on target address - abort transfer
            state_next = WriteResp;
            resp_err_status_d = Nack;
          end
          else if (cmd_dir == Write) begin
            // ImmediateDataTransfer has data in descriptor, skip FetchTxData
            if (cmd_attr == ImmediateDataTransfer) begin
              // Handle no-data case (data_length == 0)
              state_next = (data_length == 0) ? WriteResp : I3CDataWrite;
            end else begin
              state_next = FetchTxData;
            end
          end else begin
            state_next = I3CDataRead;  // Read starts immediately after address
          end
        end
      end

      // CCC_SendCCCCode: After CCC code, determine next step
      CCC_SendCCCCode: begin // problem is this doesn't send an ack, but the t-bit
        if (i3c_tx_ready_i) begin
          if (cmd_attr == AddressAssignment) begin
            // Address assignment handles static/dynamic addr internally
            state_next = I3CAddressAssignment;
          end else if (imm_use_def_byte) begin
            state_next = CCC_DefiningByte;
          end else if (is_direct_ccc) begin
            state_next = TargetAddr;  // Direct CCC needs target address
          end else if (data_length == 0) begin // should be moved higher because higher priority?
            state_next = wroc ? WriteResp : Idle;   // No data, done
          end else begin
            // Broadcast CCC with data
            if (cmd_dir == Read) begin
              state_next = I3CDataRead;
            end else begin
              state_next = FetchTxData;
            end
          end
        end
      end

      // CCC_DefiningByte: After defining byte, determine next step
      CCC_DefiningByte: begin
        if (i3c_tx_ready_i) begin
          if (is_direct_ccc) begin
            state_next = TargetAddr;
          end else if (data_length == 0) begin
            state_next = wroc ? WriteResp : Idle;
          end else begin
            // Broadcast CCC with data
            if (cmd_dir == Read) begin
              state_next = I3CDataRead;
            end else begin
              state_next = FetchTxData;
            end
          end
        end
      end

      // I3CAddressAssignment: Address Assignment CCC (static addr + dynamic addr)
      I3CAddressAssignment: begin
        // TODO: Support multi-target using addr_cmd_desc.dev_count
        if (i3c_tx_ready_i && i3c_rx_ack_valid_i && !i3c_rx_ack_i) begin
          // NACK on static address - abort transfer
          state_next = WriteResp;
          resp_err_status_d = Nack;
        end
        else if (i3c_tx_ready_i && transfer_cnt == 32'd1) begin
          // Complete after sending both static addr and dynamic addr
          state_next = wroc ? WriteResp : Idle;
        end
      end
      // I3CDataWrite: Data phase only (counter starts at 0)
      I3CDataWrite: begin

        // Done when all data_length bytes sent or if there is an Ovl Error
        if ((i3c_tx_ready_i && transfer_cnt == data_length - 32'd1) || resp_err_status_q == Ovl) begin
          // Check wroc to decide if we write response
          state_next = wroc ? WriteResp : Idle;
        end else if ((transfer_cnt & 32'd3) == 32'd3 && i3c_tx_ready_i) begin
          // Refill TX FIFO every 4 bytes (not needed for ImmediateDataTransfer since max 4 bytes)
          if (cmd_attr != ImmediateDataTransfer) begin
            state_next = FetchTxData;
          end
        end
      end

      // I3CDataRead: Data phase only (counter starts at 0)
      I3CDataRead: begin
        // overflow error handling
        if( (ibi_mode_o && ibi_queue_full_i) || (!ibi_mode_o && rx_queue_full_i)) begin
          state_next = WriteResp;
          resp_err_status_d = Ovl;
        end
        else begin
          // Transition to PushRxData when ready to push
          if (i3c_rx_valid_i) begin
            // 4 bytes accumulated OR last byte of transfer
            if (rx_byte_cnt_q == 2'd3 || i3c_rx_byte_last_i) begin
              state_next = PushRxData;
            end
          end
        end
      end
      // WriteResp: Generate Descriptor and load it to queue
      WriteResp: begin
        // AXI-like: Only transition when handshake completes (valid & ready)
        // If IBI detected
        if (ibi_mode_o) begin
          if (i3c_rx_byte_last_i) begin
            // if the ibi interrupted an ongoing transaction, restart transaction by going back to Broadcast Addr
            state_next = ibi_transaction_interrupted ? BroadcastAddr : Idle;
            ibi_transaction_interrupted_next = 1'b0;
            ibi_completed = 1'b1;
          end
          else begin
            state_next = I3CDataRead;
          end
        end
        else begin
          // Wait for handshake to complete (valid & ready both high)
          if (resp_queue_wvalid_o & resp_queue_wready_i) begin
            state_next = Idle;
          end
        end
      end

      ReadTargetAddr: begin
        if (i3c_rx_valid_i) begin
          if (abort_read_o) begin
            state_next = ibi_transaction_interrupted ? BroadcastAddr : Idle;
            ibi_transaction_interrupted_next = 1'b0;
            ibi_completed = 1'b1;
          end
          else begin
            state_next = I3CDataRead;
          end
        end
        ibi_address_byte_o = 1'b1;
        resp_err_status_d = abort_read_o ? Ovl : Success; // If we are aborting due to full RX/IBI queue, report overflow error. Otherwise no error.
      end
      default: begin
        state_next = Idle;
      end
    endcase
  end

  // Sequential state update
  always_ff @(posedge clk_i or negedge rst_ni) begin : proc_test
    if (~rst_ni) begin
      state <= Idle;
    end else begin
      state <= state_next;
    end
  end

endmodule
