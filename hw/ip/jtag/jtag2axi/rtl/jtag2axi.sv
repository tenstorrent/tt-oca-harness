// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Module: jtag2axi
// Description:
//   This module generates single-beat AXI4 transactions based on inputs
//   from JTAG scan chains. It features parametrizable address and data widths,
//   separate JTAG shift and update latches, and a shared shift register
//   architecture. Series read and write operations can be pipelined.
//
//   All stateful logic (JTAG TAP scan, command dispatch, AXI master FSM,
//   series request/response FIFOs, sticky status) lives in the TCK clock
//   domain. The AXI master interface crosses into the ACLK domain through a
//   single `axi_cdc_clearable` instance which tolerates independent warm
//   resets on `i_trstn` and `i_arstn` via its internal
//   `cdc_fifo_gray_clearable` reset coupling.
//
// Parameters:
//   ADDR_WIDTH   : Width of the AXI address bus (awaddr, araddr).
//   DATA_WIDTH   : Width of the AXI data bus (wdata, rdata). Must be a power
//                  of 2 and a multiple of 8.
//   ID_WIDTH     : Width of the AXI ID signals (awid, arid, bid, rid).
//   USER_WIDTH   : Width of the AXI USER signals (awuser, wuser, buser, aruser, ruser).
//   FIFO_DEPTH   : Max depth for series request FIFO and series read data FIFO.
//                  The value programmed via AXISeriesCtrl.pipeline_depth can be
//                  from 0 to FIFO_DEPTH. Effective depth is pipeline_depth + 1.
//   ATOP_WIDTH   : Width of the AWATOP signal (AXI5 atomic operations). Must
//                  be 6 to match the PULP AXI channel typedef layout.

module jtag2axi #(
  parameter int ADDR_WIDTH   = 52,
  parameter int DATA_WIDTH   = 64,
  parameter int ID_WIDTH     = 1,
  parameter int USER_WIDTH   = 1,
  parameter int FIFO_DEPTH   = 2,
  parameter int ATOP_WIDTH   = 6
) (
  // JTAG Interface Signals (TCK Domain)
  input  logic        i_tck,              // JTAG Test Clock
  input  logic        i_trstn,            // JTAG Test Reset (active low)

  input  logic        i_scan_in,          // JTAG Scan Data In (TDI)
  output logic        o_scan_out,         // JTAG Scan Data Out (TDO)

  input  logic        i_capture_en,       // JTAG Capture Enable (Capture-DR state)
  input  logic        i_shift_en,         // JTAG Shift Enable (Shift-DR state)
  input  logic        i_update_en,        // JTAG Update Enable (Update-DR state)

  // JTAG Scan Chain Select Signals (decoded from JTAG Instruction Register)
  input  logic        i_select_AXISingleOp,
  input  logic        i_select_AXISeriesCtrl,
  input  logic        i_select_AXISeriesDataIncr,
  input  logic        i_select_AXISeriesDataNoIncr,
  input  logic        i_select_AXISeriesDataWithErrorStatus,
  input  logic        security_disable_i,

  // AXI Interface Signals (ACLK Domain)
  input  logic        i_aclk,             // AXI Clock
  input  logic        i_arstn,            // AXI Reset (active low)

  // AXI Write Address Channel
  output logic [ID_WIDTH-1:0]     o_awid,
  output logic [ADDR_WIDTH-1:0]   o_awaddr,
  output logic [7:0]              o_awlen,
  output logic [2:0]              o_awsize,
  output logic [1:0]              o_awburst,
  output logic                    o_awlock,
  output logic [3:0]              o_awcache,
  output logic [2:0]              o_awprot,
  output logic [3:0]              o_awqos,
  output logic [3:0]              o_awregion,
  output logic [USER_WIDTH-1:0]   o_awuser,
  output logic [ATOP_WIDTH-1:0]   o_awatop,
  output logic                    o_awvalid,
  input  logic                    i_awready,

  // AXI Write Data Channel
  output logic [DATA_WIDTH-1:0]   o_wdata,
  output logic [DATA_WIDTH/8-1:0] o_wstrb,
  output logic                    o_wlast,
  output logic [USER_WIDTH-1:0]   o_wuser,
  output logic                    o_wvalid,
  input  logic                    i_wready,

  // AXI Write Response Channel
  input  logic [ID_WIDTH-1:0]     i_bid,
  input  logic [1:0]              i_bresp,
  input  logic [USER_WIDTH-1:0]   i_buser,
  input  logic                    i_bvalid,
  output logic                    o_bready,

  // AXI Read Address Channel
  output logic [ID_WIDTH-1:0]     o_arid,
  output logic [ADDR_WIDTH-1:0]   o_araddr,
  output logic [7:0]              o_arlen,
  output logic [2:0]              o_arsize,
  output logic [1:0]              o_arburst,
  output logic                    o_arlock,
  output logic [3:0]              o_arcache,
  output logic [2:0]              o_arprot,
  output logic [3:0]              o_arqos,
  output logic [3:0]              o_arregion,
  output logic [USER_WIDTH-1:0]   o_aruser,
  output logic                    o_arvalid,
  input  logic                    i_arready,

  // AXI Read Data Channel
  input  logic [ID_WIDTH-1:0]     i_rid,
  input  logic [DATA_WIDTH-1:0]   i_rdata,
  input  logic [1:0]              i_rresp,
  input  logic                    i_rlast,
  input  logic [USER_WIDTH-1:0]   i_ruser,
  input  logic                    i_rvalid,
  output logic                    o_rready
);

  `include "axi/typedef.svh"
  `include "prim_assert.sv"

  //--------------------------------------------------------------------------
  // Local Parameters and Constants
  //--------------------------------------------------------------------------

  // JTAG Operation Codes
  localparam logic [1:0] JTAG_OP_NOP = 2'b00;
  localparam logic [1:0] JTAG_OP_READ = 2'b01;
  localparam logic [1:0] JTAG_OP_WRITE = 2'b10;

  // AXI Status Codes for JTAG Capture
  localparam logic [1:0] CAPTURE_STATUS_SUCCESS = 2'b00;
  localparam logic [1:0] CAPTURE_STATUS_SLVERR = 2'b01;
  localparam logic [1:0] CAPTURE_STATUS_DECERR = 2'b10;
  localparam logic [1:0] CAPTURE_STATUS_BUSY_OR_FULL = 2'b11;

  // AXI Constants
  localparam logic [1:0] AXI_BURST_INCR = 2'b01;
  localparam logic [7:0] AXI_LEN_SINGLE = 8'b00000000;
  localparam logic [2:0] AXI_PROT_DEFAULT = 3'b000;  // Normal, Non-secure, Data
  localparam logic [3:0] AXI_CACHE_DEFAULT = 4'b0010;  // Normal Non-cacheable Non-bufferable

  localparam logic [1023:0] DEADBEEF_CONST = {32{32'hDEADBEEF}};
  logic [DATA_WIDTH-1:0] RDATA_PENDING_VALUE_CONST;
  assign RDATA_PENDING_VALUE_CONST = DEADBEEF_CONST[DATA_WIDTH-1:0];

  // Size field width: 1 bit for 8-16, 2 bits for 32-64, 3 bits for 128-1024
  localparam int SCAN_CHAIN_SIZE_FIELD_WIDTH = (DATA_WIDTH <= 16) ? 1 : (DATA_WIDTH <= 64) ? 2 : 3;
  localparam int WSTRB_FIELD_WIDTH = DATA_WIDTH / 8;
  localparam int PIPELINE_DEPTH_FIELD_BITS = (FIFO_DEPTH == 0) ? 1 : $clog2(FIFO_DEPTH + 1);

  localparam int AXISINGLEOP_OP_BITS = 2;
  localparam int AXISINGLEOP_SIZE_BITS = SCAN_CHAIN_SIZE_FIELD_WIDTH;
  localparam int AXISINGLEOP_WSTRB_BITS = WSTRB_FIELD_WIDTH;
  localparam int AXISINGLEOP_DATA_BITS = DATA_WIDTH;
  localparam int AXISINGLEOP_ADDR_BITS = ADDR_WIDTH;
  localparam int AXISINGLEOP_OP_LOW = 0;
  localparam int AXISINGLEOP_OP_HIGH = AXISINGLEOP_OP_LOW + AXISINGLEOP_OP_BITS - 1;
  localparam int AXISINGLEOP_SIZE_LOW = AXISINGLEOP_OP_HIGH + 1;
  localparam int AXISINGLEOP_SIZE_HIGH = AXISINGLEOP_SIZE_LOW + AXISINGLEOP_SIZE_BITS - 1;
  localparam int AXISINGLEOP_WSTRB_LOW = AXISINGLEOP_SIZE_HIGH + 1;
  localparam int AXISINGLEOP_WSTRB_HIGH = AXISINGLEOP_WSTRB_LOW + AXISINGLEOP_WSTRB_BITS - 1;
  localparam int AXISINGLEOP_DATA_LOW = AXISINGLEOP_WSTRB_HIGH + 1;
  localparam int AXISINGLEOP_DATA_HIGH = AXISINGLEOP_DATA_LOW + AXISINGLEOP_DATA_BITS - 1;
  localparam int AXISINGLEOP_ADDR_LOW = AXISINGLEOP_DATA_HIGH + 1;
  localparam int AXISINGLEOP_ADDR_HIGH = AXISINGLEOP_ADDR_LOW + AXISINGLEOP_ADDR_BITS - 1;
  localparam int AXISINGLEOP_LEN = AXISINGLEOP_ADDR_HIGH + 1;

  localparam int AXISERIESCTRL_OP_BITS = 2;
  localparam int AXISERIESCTRL_SIZE_BITS = SCAN_CHAIN_SIZE_FIELD_WIDTH;
  localparam int AXISERIESCTRL_PD_BITS = PIPELINE_DEPTH_FIELD_BITS;
  localparam int AXISERIESCTRL_ADDR_BITS = ADDR_WIDTH;
  localparam int AXISERIESCTRL_RESET_BITS = 1;
  localparam int AXISERIESCTRL_OP_LOW = 0;
  localparam int AXISERIESCTRL_OP_HIGH = AXISERIESCTRL_OP_LOW + AXISERIESCTRL_OP_BITS - 1;
  localparam int AXISERIESCTRL_SIZE_LOW = AXISERIESCTRL_OP_HIGH + 1;
  localparam int AXISERIESCTRL_SIZE_HIGH = AXISERIESCTRL_SIZE_LOW + AXISERIESCTRL_SIZE_BITS - 1;
  localparam int AXISERIESCTRL_PD_LOW = AXISERIESCTRL_SIZE_HIGH + 1;
  localparam int AXISERIESCTRL_PD_HIGH = AXISERIESCTRL_PD_LOW + AXISERIESCTRL_PD_BITS - 1;
  localparam int AXISERIESCTRL_ADDR_LOW = AXISERIESCTRL_PD_HIGH + 1;
  localparam int AXISERIESCTRL_ADDR_HIGH = AXISERIESCTRL_ADDR_LOW + AXISERIESCTRL_ADDR_BITS - 1;
  localparam int AXISERIESCTRL_RESET_LOW = AXISERIESCTRL_ADDR_HIGH + 1;
  localparam int AXISERIESCTRL_RESET_HIGH = AXISERIESCTRL_RESET_LOW + AXISERIESCTRL_RESET_BITS - 1;
  localparam int AXISERIESCTRL_LEN = AXISERIESCTRL_RESET_HIGH + 1;

  localparam int SERIES_DATA_MAX_MAPPED_BITS = DATA_WIDTH;
  localparam int AXISERIESDATAINCR_MAX_LEN = SERIES_DATA_MAX_MAPPED_BITS;
  localparam int AXISERIESDATANOINCR_MAX_LEN = SERIES_DATA_MAX_MAPPED_BITS;
  localparam int AXISERIESDATAWITHERRORSTATUS_MAX_LEN = SERIES_DATA_MAX_MAPPED_BITS + 1;

  function automatic integer max4(input integer a, input integer b, input integer c,
                                  input integer d);
    begin
      integer ab, cd;
      ab = (a > b) ? a : b;
      cd = (c > d) ? c : d;
      return (ab > cd) ? ab : cd;
    end
  endfunction

  // Convert AXI size value to number of bits (8, 16, 32, ..., 1024)
  function automatic int size_to_bits(input logic [2:0] size_val);
    return 8 << size_val;  // 8 * 2^size_val
  endfunction

  // Convert AXI size value to number of bytes (1, 2, 4, ..., 128)
  function automatic int size_to_bytes(input logic [2:0] size_val);
    return 1 << size_val;  // 2^size_val
  endfunction

  localparam int SHARED_SR_LEN = max4(
      AXISINGLEOP_LEN,
      AXISERIESCTRL_LEN,
      AXISERIESDATAINCR_MAX_LEN,
      AXISERIESDATAWITHERRORSTATUS_MAX_LEN
  );
  localparam int SERIES_RSP_FIFO_SIZE = FIFO_DEPTH + 1;
  localparam int CDC_LOG_DEPTH = (FIFO_DEPTH + 2 <= 2) ? 1 : $clog2(FIFO_DEPTH + 2);
  localparam int unsigned BEAT_BYTES = DATA_WIDTH / 8;
  localparam int unsigned BYTE_OFFSET_BITS = (BEAT_BYTES <= 1) ? 0 : $clog2(BEAT_BYTES);

  //--------------------------------------------------------------------------
  // AXI Channel and Request/Response Typedefs (PULP AXI)
  //--------------------------------------------------------------------------
  typedef logic [ID_WIDTH-1:0] j2a_id_t;
  typedef logic [ADDR_WIDTH-1:0] j2a_addr_t;
  typedef logic [DATA_WIDTH-1:0] j2a_data_t;
  typedef logic [DATA_WIDTH/8-1:0] j2a_strb_t;
  typedef logic [USER_WIDTH-1:0] j2a_user_t;
  `AXI_TYPEDEF_AW_CHAN_T(j2a_aw_t, j2a_addr_t, j2a_id_t, j2a_user_t)
  `AXI_TYPEDEF_W_CHAN_T(j2a_w_t, j2a_data_t, j2a_strb_t, j2a_user_t)
  `AXI_TYPEDEF_B_CHAN_T(j2a_b_t, j2a_id_t, j2a_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(j2a_ar_t, j2a_addr_t, j2a_id_t, j2a_user_t)
  `AXI_TYPEDEF_R_CHAN_T(j2a_r_t, j2a_data_t, j2a_id_t, j2a_user_t)
  `AXI_TYPEDEF_REQ_T(j2a_req_t, j2a_aw_t, j2a_w_t, j2a_ar_t)
  `AXI_TYPEDEF_RESP_T(j2a_resp_t, j2a_b_t, j2a_r_t)

  // Beat-lane helpers for series transfers. Offset is current_addr modulo
  // the data-bus width in bytes. SingleOp keeps host-packed WSTRB/DATA and
  // does not use these.
  function automatic int unsigned beat_byte_offset(input logic [ADDR_WIDTH-1:0] addr);
    localparam int unsigned OffW = (BYTE_OFFSET_BITS == 0) ? 1 : BYTE_OFFSET_BITS;
    logic [OffW-1:0] offset_bits;
    offset_bits = '0;
    if (BYTE_OFFSET_BITS != 0) begin
      offset_bits = addr[OffW-1:0];
    end
    return (BYTE_OFFSET_BITS == 0) ? 0 : int'(offset_bits);
  endfunction

  function automatic j2a_strb_t series_lane_wstrb(input logic [ADDR_WIDTH-1:0] addr,
                                                  input logic [2:0] axsize);
    automatic int unsigned offset = beat_byte_offset(addr);
    automatic int unsigned num_bytes = size_to_bytes(axsize);
    automatic j2a_strb_t mask;
    if (num_bytes >= BEAT_BYTES) begin
      return '1;
    end
    mask = j2a_strb_t'((j2a_strb_t'(1) << num_bytes) - 1);
    return j2a_strb_t'(mask << offset);
  endfunction

  function automatic j2a_data_t series_lane_wdata(input j2a_data_t data,
                                                  input logic [ADDR_WIDTH-1:0] addr);
    automatic int unsigned offset = beat_byte_offset(addr);
    return j2a_data_t'(data << (8 * offset));
  endfunction

  function automatic j2a_data_t series_lane_rdata(input j2a_data_t rdata,
                                                  input logic [ADDR_WIDTH-1:0] addr);
    automatic int unsigned offset = beat_byte_offset(addr);
    return j2a_data_t'(rdata >> (8 * offset));
  endfunction

  //--------------------------------------------------------------------------
  // Parameter Validation Assertions
  //--------------------------------------------------------------------------
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(DataWidthRangeOk_A, (DATA_WIDTH >= 8) && (DATA_WIDTH <= 1024))
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(DataWidthPow2_A, (DATA_WIDTH & (DATA_WIDTH - 1)) == 0)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(AtopWidthIs6_A, ATOP_WIDTH == 6)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(AddrWidthCoversBeatOffset_A, ADDR_WIDTH >= $clog2
                                    (DATA_WIDTH / 8))

  //--------------------------------------------------------------------------
  // JTAG TDR Shared Shift Register and Update Latches (TCK Domain)
  //--------------------------------------------------------------------------
  logic [SHARED_SR_LEN-1:0] shift_register_q_tclk;
  logic [SHARED_SR_LEN-1:0] update_register_q_tclk;
  logic [SHARED_SR_LEN-1:0] capture_data_tclk;

  logic [SCAN_CHAIN_SIZE_FIELD_WIDTH-1:0] latched_series_size_for_len_tclk;
  logic [$clog2(SHARED_SR_LEN+1)-1:0] active_instr_len_tclk;

  always_ff @(negedge i_tck or negedge i_trstn) begin
    if (!i_trstn) begin
      latched_series_size_for_len_tclk <= '0;
    end else begin
      if (i_update_en && i_select_AXISeriesCtrl && !security_disable_i) begin
        latched_series_size_for_len_tclk <= shift_register_q_tclk[AXISERIESCTRL_SIZE_HIGH : AXISERIESCTRL_SIZE_LOW];
      end
    end
  end

  always_comb begin
    active_instr_len_tclk = SHARED_SR_LEN;
    if (i_select_AXISingleOp) begin
      active_instr_len_tclk = AXISINGLEOP_LEN;
    end else if (i_select_AXISeriesCtrl) begin
      active_instr_len_tclk = AXISERIESCTRL_LEN;
    end else if (i_select_AXISeriesDataIncr || i_select_AXISeriesDataNoIncr || i_select_AXISeriesDataWithErrorStatus) begin
      automatic int mapped_data_bits_local;
      mapped_data_bits_local = size_to_bits(3'(latched_series_size_for_len_tclk));
      if (mapped_data_bits_local > DATA_WIDTH) mapped_data_bits_local = DATA_WIDTH;
      if (i_select_AXISeriesDataIncr || i_select_AXISeriesDataNoIncr) begin
        active_instr_len_tclk = mapped_data_bits_local;
      end else if (i_select_AXISeriesDataWithErrorStatus) begin
        active_instr_len_tclk = mapped_data_bits_local + 1;
      end
    end
    if (active_instr_len_tclk == 0 &&
            (i_select_AXISingleOp || i_select_AXISeriesCtrl || i_select_AXISeriesDataIncr ||
             i_select_AXISeriesDataNoIncr || i_select_AXISeriesDataWithErrorStatus) ) begin
      active_instr_len_tclk = 1;
    end
    if (active_instr_len_tclk > SHARED_SR_LEN) begin
      active_instr_len_tclk = SHARED_SR_LEN;
    end
  end

  logic [SHARED_SR_LEN-1:0] shift_register_d_tclk;

  always_comb begin
    automatic logic [SHARED_SR_LEN-1:0]            next_sr_val;
    automatic logic [$clog2(SHARED_SR_LEN+1)-1:0] current_len;

    shift_register_d_tclk = shift_register_q_tclk;
    current_len = active_instr_len_tclk;
    next_sr_val = shift_register_q_tclk;

    if (i_capture_en) begin
      shift_register_d_tclk = capture_data_tclk;
    end else if (i_shift_en) begin
      if (current_len > 0 && current_len <= SHARED_SR_LEN) begin
        next_sr_val[current_len-1] = i_scan_in;
        for (int bit_idx = 0; bit_idx < SHARED_SR_LEN - 1; bit_idx = bit_idx + 1) begin
          if (bit_idx < int'(current_len) - 1) begin
            next_sr_val[bit_idx] = shift_register_q_tclk[bit_idx+1];
          end
        end
      end
      shift_register_d_tclk = next_sr_val;
    end
  end

  always_ff @(posedge i_tck or negedge i_trstn) begin
    if (!i_trstn) begin
      shift_register_q_tclk <= '0;
    end else begin
      shift_register_q_tclk <= shift_register_d_tclk;
    end
  end

  always_ff @(negedge i_tck or negedge i_trstn) begin
    if (!i_trstn) begin
      update_register_q_tclk <= '0;
    end else begin
      if (i_update_en && !security_disable_i) begin
        update_register_q_tclk <= shift_register_q_tclk;
      end
    end
  end
  assign o_scan_out = shift_register_q_tclk[0];

  //--------------------------------------------------------------------------
  // JTAG Scan Chain Data Extraction (TCK Domain)
  //--------------------------------------------------------------------------
  logic [AXISINGLEOP_OP_BITS-1:0]    single_op_op_tclk;
  logic [AXISINGLEOP_SIZE_BITS-1:0]  single_op_size_tclk;
  logic [AXISINGLEOP_WSTRB_BITS-1:0] single_op_wstrb_tclk;
  logic [AXISINGLEOP_DATA_BITS-1:0]  single_op_data_tclk;
  logic [AXISINGLEOP_ADDR_BITS-1:0]  single_op_addr_tclk;

  assign single_op_op_tclk    = update_register_q_tclk[AXISINGLEOP_OP_HIGH    : AXISINGLEOP_OP_LOW];
  assign single_op_size_tclk  = update_register_q_tclk[AXISINGLEOP_SIZE_HIGH  : AXISINGLEOP_SIZE_LOW];
  assign single_op_wstrb_tclk = update_register_q_tclk[AXISINGLEOP_WSTRB_HIGH : AXISINGLEOP_WSTRB_LOW];
  assign single_op_data_tclk  = update_register_q_tclk[AXISINGLEOP_DATA_HIGH  : AXISINGLEOP_DATA_LOW];
  assign single_op_addr_tclk  = update_register_q_tclk[AXISINGLEOP_ADDR_HIGH  : AXISINGLEOP_ADDR_LOW];

  logic [DATA_WIDTH-1:0] series_data_val_tclk;
  assign series_data_val_tclk = update_register_q_tclk[DATA_WIDTH-1:0];

  logic [DATA_WIDTH-1:0] series_data_errstat_val_tclk;
  logic                  series_data_errstat_incr_stat_bit_tclk;

  always_comb begin
    automatic logic [$clog2(SHARED_SR_LEN+1)-1:0] current_mapped_data_len_local;
    automatic int num_bytes_to_copy;
    series_data_errstat_val_tclk = '0;

    current_mapped_data_len_local = size_to_bits(3'(latched_series_size_for_len_tclk));
    if (current_mapped_data_len_local > DATA_WIDTH) current_mapped_data_len_local = DATA_WIDTH;

    num_bytes_to_copy = int'(current_mapped_data_len_local) >> 3;  // bits-to-bytes: divide by 8
    for (int byte_idx = 0; byte_idx < DATA_WIDTH / 8; byte_idx++) begin
      if (byte_idx < num_bytes_to_copy) begin
        series_data_errstat_val_tclk[byte_idx*8+:8] = update_register_q_tclk[byte_idx*8+:8];
      end
    end

    if (current_mapped_data_len_local < SHARED_SR_LEN) begin
      series_data_errstat_incr_stat_bit_tclk = update_register_q_tclk[current_mapped_data_len_local];
    end else begin
      series_data_errstat_incr_stat_bit_tclk = 1'b0;
    end
  end

  //--------------------------------------------------------------------------
  // TCK Authoritative State
  //--------------------------------------------------------------------------

  // Single-op transaction buffer
  logic                                   single_tx_req_valid_tclk;
  logic [1:0]                             single_tx_op_tclk;
  logic [ADDR_WIDTH-1:0]                  single_tx_addr_tclk;
  logic [DATA_WIDTH-1:0]                  single_tx_data_tclk;
  logic [SCAN_CHAIN_SIZE_FIELD_WIDTH-1:0] single_tx_axi_size_tclk;
  logic [WSTRB_FIELD_WIDTH-1:0]           single_tx_wstrb_tclk;

  // Series control state
  logic [AXISERIESCTRL_SIZE_BITS-1:0] series_ctrl_size_tclk_r;
  logic [AXISERIESCTRL_PD_BITS-1:0]   series_ctrl_pipeline_depth_tclk_r;
  logic [ADDR_WIDTH-1:0]              series_ctrl_address_tclk_r;
  logic [1:0]                         series_ctrl_op_mode_tclk_r;

  // Status registers
  logic                  single_op_pending_tclk;
  logic                  series_errstat_pending_tclk;
  logic [1:0]            last_single_op_status_tclk;
  logic [DATA_WIDTH-1:0] last_read_data_tclk;
  logic                  last_single_op_was_read_tclk;
  logic [1:0]            sticky_axi_status_tclk;
  logic                  sticky_axi_status_full_tclk;

  // Read pipeline preload counter
  logic [PIPELINE_DEPTH_FIELD_BITS-1:0] series_read_preload_count_tclk;

  // Counters
  // `plain_reads_pending_tclk`: plain series reads enqueued by JTAG but not
  //   yet completed on AXI. Used for capture priority on AXISeriesDataIncr/
  //   NoIncr reads.
  // `series_reads_in_flight_tclk`: series reads (plain or errstat) with AR
  //   issued but R not yet returned. Used for the pipeline_depth
  //   backpressure on JTAG update accept.
  logic [$clog2(FIFO_DEPTH+2)-1:0] plain_reads_pending_tclk;
  logic [$clog2(FIFO_DEPTH+2)-1:0] series_reads_in_flight_tclk;
  // `current_tx_stale_tclk`: marks the FSM's in-flight series read as
  //   stale (issued under a prior CTRL programming that has since been
  //   replaced). Its AXI response must complete normally on the bus but
  //   must not be pushed into the freshly flushed series-rsp FIFO.
  logic                            current_tx_stale_tclk;
  // Combinational pulse asserted on a CTRL Update-DR with a non-NOP op.
  // A new CTRL programming flushes all queued series request/response
  // state from any prior programming.
  logic                            ctrl_flush_pulse_tclk;
  // `series_reads_pushed_tclk`: total series read requests enqueued via
  //   JTAG Update-DR since the last non-NOP CTRL programming. Bounded at
  //   `pipeline_depth + 1` so that a host that issues more SeriesData
  //   scans than the configured pipeline depth (e.g. the standard
  //   "1 issue + N readback" pattern) does not over-queue requests and
  //   leak stale rsp-FIFO entries into subsequent operations.
  logic [$clog2(FIFO_DEPTH+2)-1:0] series_reads_pushed_tclk;

  //--------------------------------------------------------------------------
  // Series Request FIFO (TCK Domain)
  //--------------------------------------------------------------------------
  typedef struct packed {
    logic [ADDR_WIDTH-1:0]                  addr;
    logic [DATA_WIDTH-1:0]                  data;
    logic [1:0]                             op;
    logic [SCAN_CHAIN_SIZE_FIELD_WIDTH-1:0] jtag_size;
    logic                                   increment_addr;
    logic                                   is_series_data_with_error_status_op;
  } series_request_fifo_entry_t;

  logic [$clog2(FIFO_DEPTH+2)-1:0]      series_request_fifo_count_tclk;
  logic                                 series_request_fifo_full_tclk;
  logic                                 series_request_fifo_empty_tclk;
  logic                                 series_request_fifo_push_tclk;
  logic                                 series_request_fifo_pop_tclk;
  series_request_fifo_entry_t           series_request_fifo_din_tclk;
  series_request_fifo_entry_t           series_request_fifo_dout_tclk;

  //--------------------------------------------------------------------------
  // Series Response FIFO
  //--------------------------------------------------------------------------
  typedef struct packed {
    logic [DATA_WIDTH-1:0] rdata;
    logic [1:0]            rresp;
  } series_read_rsp_t;

  logic [$clog2(SERIES_RSP_FIFO_SIZE+1)-1:0] series_rsp_fifo_count_tclk;
  logic                                      series_rsp_fifo_full_tclk;
  logic                                      series_rsp_fifo_empty_tclk;
  logic                                      series_rsp_fifo_push_tclk;
  logic                                      series_rsp_fifo_pop_tclk;
  series_read_rsp_t                          series_rsp_fifo_din_tclk;
  series_read_rsp_t                          series_rsp_fifo_dout_tclk;

  //--------------------------------------------------------------------------
  // AXI FSM
  //--------------------------------------------------------------------------
  typedef enum logic [2:0] {
    AXI_IDLE,
    AXI_SEND_ADDR_W,
    AXI_SEND_DATA_W,
    AXI_WAIT_BRESP,
    AXI_SEND_ADDR_R,
    AXI_WAIT_RDATA,
    AXI_UPDATE_STATUS
  } axi_state_e;
  axi_state_e axi_state_q_tclk, axi_state_d_tclk;

  // In-flight transaction parameters
  logic [1:0]                             current_op_tclk;
  logic [ADDR_WIDTH-1:0]                  current_addr_tclk;
  logic [DATA_WIDTH-1:0]                  current_data_tclk;
  logic [SCAN_CHAIN_SIZE_FIELD_WIDTH-1:0] current_jtag_size_tclk;
  logic [WSTRB_FIELD_WIDTH-1:0]           current_custom_wstrb_tclk;
  logic                                   current_use_custom_wstrb_tclk;
  logic                                   current_incr_series_addr_tclk;
  logic                                   current_tx_is_series_read_tclk;
  logic                                   current_tx_is_from_single_buffer_tclk;
  logic                                   current_is_series_data_with_error_status_op_tclk;

  // Derived
  logic [2:0]                   current_axi_axsize_tclk;
  logic [WSTRB_FIELD_WIDTH-1:0] current_wstrb_tclk;
  logic                         axi_transaction_in_progress_tclk;

  // FSM combinational completion flags
  logic                  fsm_updates_bresp_status_tclk_comb;
  logic                  fsm_updates_rdata_status_tclk_comb;
  logic [1:0]            next_status_tclk_comb;
  logic [DATA_WIDTH-1:0] next_read_data_tclk_comb;

  //--------------------------------------------------------------------------
  // Internal AXI master req/resp (TCK Domain)
  //--------------------------------------------------------------------------
  j2a_req_t  src_req;
  j2a_resp_t src_resp;
  j2a_req_t  dst_req;
  j2a_resp_t dst_resp;

  // ACLK-domain TLR-safe output stage. Fall-through registers eliminate
  // the normal-operation ACLK bubble while retaining each beat when the
  // fabric stalls. AW and W are joined before either is exposed.
  j2a_aw_t aw_buf;
  j2a_w_t  w_buf;
  j2a_ar_t ar_buf;

  logic aw_buf_valid;
  logic w_buf_valid;
  logic ar_buf_valid;
  logic aw_buf_ready;
  logic w_buf_ready;
  logic ar_buf_ready;
  logic aw_input_valid;
  logic w_input_valid;
  logic ar_input_valid;
  logic [1:0] write_join_ready;
  logic       write_pair_valid;
  logic       write_pair_ready;
  logic [1:0] write_fork_valid;
  logic       write_pair_partial;
  logic       write_pair_flush;

  logic dst_clear_pending;
  logic dst_clear_pending_q;
  logic dst_clear_start;

  logic write_discard_rsp_q;
  logic read_discard_rsp_q;

  localparam logic [1:0] OUTSTANDING_MAX = 2'b11;
  logic [1:0] write_outstanding_q;
  logic [1:0] write_outstanding_d;
  logic [1:0] read_outstanding_q;
  logic [1:0] read_outstanding_d;
  logic [1:0] orphan_b_count_q;
  logic [1:0] orphan_b_count_d;
  logic [1:0] orphan_r_count_q;
  logic [1:0] orphan_r_count_d;

  logic ar_handshake;
  logic b_handshake;
  logic r_handshake;
  logic r_last_handshake;
  logic write_complete;
  logic write_completion_is_orphan;
  logic read_completion_is_orphan;

  //--------------------------------------------------------------------------
  // AXI CDC: bridges the internal TCK master to the external ACLK AXI pins
  //--------------------------------------------------------------------------
  axi_cdc_clearable #(
    .aw_chan_t         (j2a_aw_t),
    .w_chan_t          (j2a_w_t),
    .b_chan_t          (j2a_b_t),
    .ar_chan_t         (j2a_ar_t),
    .r_chan_t          (j2a_r_t),
    .axi_req_t         (j2a_req_t),
    .axi_resp_t        (j2a_resp_t),
    .LogDepth          (CDC_LOG_DEPTH),
    .SyncStages        (3),
    .ClearOnAsyncReset (1'b1)
  ) u_axi_cdc (
    .src_clk_i           (i_tck),
    .src_rst_ni          (i_trstn),
    .src_clear_i         (1'b0),
    .src_clear_pending_o (/* unused */),
    .src_req_i           (src_req),
    .src_resp_o          (src_resp),
    .dst_clk_i           (i_aclk),
    .dst_rst_ni          (i_arstn),
    .dst_clear_i         (1'b0),
    .dst_clear_pending_o (dst_clear_pending),
    .dst_req_o           (dst_req),
    .dst_resp_i          (dst_resp)
  );

  //--------------------------------------------------------------------------
  // ACLK-domain TLR-safe AXI output stage
  //--------------------------------------------------------------------------

  assign dst_clear_start = dst_clear_pending && !dst_clear_pending_q;

  // Do not consume a CDC beat after its clear sequence has started. A
  // partially assembled write is flushed; a complete pair is drained.
  assign dst_resp.aw_ready = !dst_clear_pending && aw_buf_ready &&
                               (write_outstanding_q != OUTSTANDING_MAX);
  assign dst_resp.w_ready  = !dst_clear_pending && w_buf_ready &&
                               (write_outstanding_q != OUTSTANDING_MAX);
  assign dst_resp.ar_ready = !dst_clear_pending && ar_buf_ready &&
                               (read_outstanding_q != OUTSTANDING_MAX);

  assign aw_input_valid = dst_req.aw_valid && dst_resp.aw_ready;
  assign w_input_valid  = dst_req.w_valid && dst_resp.w_ready;
  assign ar_input_valid = dst_req.ar_valid && dst_resp.ar_ready;
  assign write_pair_partial = aw_buf_valid ^ w_buf_valid;
  assign write_pair_flush   = dst_clear_start && write_pair_partial;

  // Each fall-through register accepts an independent CDC beat. stream_join
  // waits for the complete write pair; stream_fork lets AW and W handshake
  // independently while completing the input pair exactly once.
  fall_through_register #(
    .T(j2a_aw_t)
  ) u_aw_ft_reg (
    .clk_i      (i_aclk),
    .rst_ni     (i_arstn),
    .clr_i       (write_pair_flush),
    .testmode_i(1'b0),
    .valid_i    (aw_input_valid),
    .ready_o    (aw_buf_ready),
    .data_i     (dst_req.aw),
    .valid_o    (aw_buf_valid),
    .ready_i    (write_join_ready[1]),
    .data_o     (aw_buf)
  );

  fall_through_register #(
    .T(j2a_w_t)
  ) u_w_ft_reg (
    .clk_i      (i_aclk),
    .rst_ni     (i_arstn),
    .clr_i       (write_pair_flush),
    .testmode_i(1'b0),
    .valid_i    (w_input_valid),
    .ready_o    (w_buf_ready),
    .data_i     (dst_req.w),
    .valid_o    (w_buf_valid),
    .ready_i    (write_join_ready[0]),
    .data_o     (w_buf)
  );

  stream_join #(
    .N_INP(2)
  ) u_write_join (
    .inp_valid_i ({aw_buf_valid, w_buf_valid}),
    .inp_ready_o (write_join_ready),
    .oup_valid_o (write_pair_valid),
    .oup_ready_i (write_pair_ready)
  );

  stream_fork #(
    .N_OUP(2)
  ) u_write_fork (
    .clk_i   (i_aclk),
    .rst_ni  (i_arstn),
    .valid_i (write_pair_valid),
    .ready_o (write_pair_ready),
    .valid_o (write_fork_valid),
    .ready_i ({i_awready, i_wready})
  );

  fall_through_register #(
    .T(j2a_ar_t)
  ) u_ar_ft_reg (
    .clk_i      (i_aclk),
    .rst_ni     (i_arstn),
    .clr_i       (1'b0),
    .testmode_i(1'b0),
    .valid_i    (ar_input_valid),
    .ready_o    (ar_buf_ready),
    .data_i     (dst_req.ar),
    .valid_o    (ar_buf_valid),
    .ready_i    (i_arready),
    .data_o     (ar_buf)
  );

  assign o_awvalid = write_fork_valid[1];
  assign o_wvalid  = write_fork_valid[0];
  assign o_arvalid = ar_buf_valid;

  assign ar_handshake = o_arvalid && i_arready;
  assign write_complete = write_pair_valid && write_pair_ready;

  assign write_completion_is_orphan = write_discard_rsp_q || dst_clear_start;
  assign read_completion_is_orphan  = read_discard_rsp_q || dst_clear_start;

  assign o_awid     = aw_buf.id;
  assign o_awaddr   = aw_buf.addr;
  assign o_awlen    = aw_buf.len;
  assign o_awsize   = aw_buf.size;
  assign o_awburst  = aw_buf.burst;
  assign o_awlock   = aw_buf.lock;
  assign o_awcache  = aw_buf.cache;
  assign o_awprot   = aw_buf.prot;
  assign o_awqos    = aw_buf.qos;
  assign o_awregion = aw_buf.region;
  assign o_awuser   = aw_buf.user;
  assign o_awatop   = aw_buf.atop;

  assign o_wdata = w_buf.data;
  assign o_wstrb = w_buf.strb;
  assign o_wlast = w_buf.last;
  assign o_wuser = w_buf.user;

  assign o_arid     = ar_buf.id;
  assign o_araddr   = ar_buf.addr;
  assign o_arlen    = ar_buf.len;
  assign o_arsize   = ar_buf.size;
  assign o_arburst  = ar_buf.burst;
  assign o_arlock   = ar_buf.lock;
  assign o_arcache  = ar_buf.cache;
  assign o_arprot   = ar_buf.prot;
  assign o_arqos    = ar_buf.qos;
  assign o_arregion = ar_buf.region;
  assign o_aruser   = ar_buf.user;

  // All requests outstanding when a clear starts belong to the old JTAG
  // session.  Consume their ordered responses locally instead of allowing a
  // stale B or R beat to satisfy the first request of the new session.
  // A slave may return a response in the same cycle as the final request
  // handshake.  Include that just-completed request here rather than
  // inserting a response-channel bubble.
  assign o_bready = ((write_outstanding_q != '0) || write_complete) &&
                      ((orphan_b_count_q != '0) ||
                       (write_complete && write_completion_is_orphan) ||
                       (!dst_clear_pending && dst_req.b_ready));
  assign o_rready = ((read_outstanding_q != '0) || ar_handshake) &&
                      ((orphan_r_count_q != '0) ||
                       (ar_handshake && read_completion_is_orphan) ||
                       (!dst_clear_pending && dst_req.r_ready));

  assign dst_resp.b_valid = i_bvalid &&
                              ((write_outstanding_q != '0) || write_complete) &&
                              (orphan_b_count_q == '0) && !dst_clear_pending;
  assign dst_resp.b.id     = i_bid;
  assign dst_resp.b.resp   = i_bresp;
  assign dst_resp.b.user   = i_buser;
  assign dst_resp.r_valid  = i_rvalid &&
                               ((read_outstanding_q != '0) || ar_handshake) &&
                               (orphan_r_count_q == '0) && !dst_clear_pending;
  assign dst_resp.r.id     = i_rid;
  assign dst_resp.r.data   = i_rdata;
  assign dst_resp.r.resp   = i_rresp;
  assign dst_resp.r.last   = i_rlast;
  assign dst_resp.r.user   = i_ruser;

  assign b_handshake      = i_bvalid && o_bready;
  assign r_handshake      = i_rvalid && o_rready;
  assign r_last_handshake = r_handshake && i_rlast;

  // Track all fabric requests awaiting responses and the ordered prefix of
  // those responses that must be discarded.  A new clear reclassifies every
  // request remaining after the current cycle as orphaned.
  always_comb begin
    write_outstanding_d = write_outstanding_q;
    unique case ({
      write_complete, b_handshake
    })
      2'b10: write_outstanding_d = write_outstanding_q + 2'd1;
      2'b01: write_outstanding_d = write_outstanding_q - 2'd1;
      default: write_outstanding_d = write_outstanding_q;
    endcase

    read_outstanding_d = read_outstanding_q;
    unique case ({
      ar_handshake, r_last_handshake
    })
      2'b10: read_outstanding_d = read_outstanding_q + 2'd1;
      2'b01: read_outstanding_d = read_outstanding_q - 2'd1;
      default: read_outstanding_d = read_outstanding_q;
    endcase

    orphan_b_count_d = orphan_b_count_q;
    if (dst_clear_start) begin
      orphan_b_count_d = write_outstanding_d;
    end else begin
      unique case ({
        write_complete && write_completion_is_orphan, b_handshake && (orphan_b_count_q != '0)
      })
        2'b10: orphan_b_count_d = orphan_b_count_q + 2'd1;
        2'b01: orphan_b_count_d = orphan_b_count_q - 2'd1;
        default: orphan_b_count_d = orphan_b_count_q;
      endcase
    end

    orphan_r_count_d = orphan_r_count_q;
    if (dst_clear_start) begin
      orphan_r_count_d = read_outstanding_d;
    end else begin
      unique case ({
        ar_handshake && read_completion_is_orphan, r_last_handshake && (orphan_r_count_q != '0)
      })
        2'b10: orphan_r_count_d = orphan_r_count_q + 2'd1;
        2'b01: orphan_r_count_d = orphan_r_count_q - 2'd1;
        default: orphan_r_count_d = orphan_r_count_q;
      endcase
    end
  end

  always_ff @(posedge i_aclk or negedge i_arstn) begin
    if (!i_arstn) begin
      dst_clear_pending_q <= 1'b0;
      write_discard_rsp_q <= 1'b0;
      read_discard_rsp_q  <= 1'b0;
      write_outstanding_q <= '0;
      read_outstanding_q  <= '0;
      orphan_b_count_q    <= '0;
      orphan_r_count_q    <= '0;
    end else begin
      dst_clear_pending_q <= dst_clear_pending;
      write_outstanding_q <= write_outstanding_d;
      read_outstanding_q  <= read_outstanding_d;
      orphan_b_count_q    <= orphan_b_count_d;
      orphan_r_count_q    <= orphan_r_count_d;

      if (dst_clear_start) begin
        // The fall-through registers flush a lone write half. A
        // complete pair, including one with a channel already
        // accepted, remains visible to stream_fork and drains.
        if (write_pair_partial) begin
          write_discard_rsp_q <= 1'b0;
        end else if (write_pair_valid) begin
          write_discard_rsp_q <= 1'b1;
        end
        if (ar_buf_valid) begin
          read_discard_rsp_q <= 1'b1;
        end
      end

      if (write_complete) begin
        write_discard_rsp_q <= 1'b0;
      end
      if (ar_handshake) begin
        read_discard_rsp_q <= 1'b0;
      end
    end
  end

`ifndef SYNTHESIS
  `OCAH_OT_ASSERT(AwValidStable_A, o_awvalid && !i_awready |=> o_awvalid && $stable(aw_buf),
                  i_aclk, !i_arstn)
  `OCAH_OT_ASSERT(WValidStable_A, o_wvalid && !i_wready |=> o_wvalid && $stable(w_buf), i_aclk,
                  !i_arstn)
  `OCAH_OT_ASSERT(ArValidStable_A, o_arvalid && !i_arready |=> o_arvalid && $stable(ar_buf),
                  i_aclk, !i_arstn)
  `OCAH_OT_ASSERT(AwHasWriteData_A, o_awvalid |-> w_buf_valid, i_aclk, !i_arstn)
  `OCAH_OT_ASSERT(WaHasWriteAddress_A, o_wvalid |-> aw_buf_valid, i_aclk, !i_arstn)
`endif

  //--------------------------------------------------------------------------
  // Series Request FIFO Storage (TCK)
  //--------------------------------------------------------------------------
  assign ctrl_flush_pulse_tclk = i_update_en && !security_disable_i &&
        i_select_AXISeriesCtrl &&
        (update_register_q_tclk[AXISERIESCTRL_OP_HIGH:AXISERIESCTRL_OP_LOW] != JTAG_OP_NOP);

  localparam int unsigned ReqFifoDepth = FIFO_DEPTH + 1;
  localparam int unsigned ReqFifoWidth = $bits(series_request_fifo_entry_t);

  logic req_fifo_full_internal_tclk;
  logic req_fifo_clr_tclk;

  assign req_fifo_clr_tclk =
        (security_disable_i && (axi_state_q_tclk == AXI_IDLE)) ||
        ctrl_flush_pulse_tclk;

  prim_fifo_sync #(
    .Width            (ReqFifoWidth),
    .Depth            (ReqFifoDepth),
    .Pass             (1'b0),
    .OutputZeroIfEmpty(1'b0),
    .NeverClears      (1'b0),
    .Secure           (1'b0)
  ) u_series_request_fifo (
    .clk_i   (i_tck),
    .rst_ni  (i_trstn),
    .clr_i   (req_fifo_clr_tclk),
    .wvalid_i(series_request_fifo_push_tclk),
    .wready_o(/* unused, full handled below */),
    .wdata_i (series_request_fifo_din_tclk),
    .rvalid_o(/* unused */),
    .rready_i(series_request_fifo_pop_tclk),
    .rdata_o (series_request_fifo_dout_tclk),
    .full_o  (req_fifo_full_internal_tclk),
    .depth_o (series_request_fifo_count_tclk),
    .err_o   ()
  );

  logic [$clog2(FIFO_DEPTH+2)-1:0] series_request_max_entries_tclk;
  assign series_request_max_entries_tclk = series_ctrl_pipeline_depth_tclk_r + 1;
  assign series_request_fifo_empty_tclk = (series_request_fifo_count_tclk == '0);
  assign series_request_fifo_full_tclk  =
        req_fifo_full_internal_tclk ||
        (series_request_fifo_count_tclk >= series_request_max_entries_tclk);

  //--------------------------------------------------------------------------
  // Series Response FIFO Storage (TCK)
  //--------------------------------------------------------------------------
  // Push when the FSM completes a plain series read's R-last beat.
  // A response generated by a stale (pre-flush) transaction is allowed to
  // complete on the AXI bus but must not enter the freshly cleared
  // series-rsp FIFO; gate the push on `current_tx_stale_tclk`.
  assign series_rsp_fifo_push_tclk =
        fsm_updates_rdata_status_tclk_comb && src_resp.r.last &&
        current_tx_is_series_read_tclk &&
        !current_is_series_data_with_error_status_op_tclk &&
        !current_tx_stale_tclk;
  assign series_rsp_fifo_din_tclk.rdata =
        series_lane_rdata(src_resp.r.data, current_addr_tclk);
  assign series_rsp_fifo_din_tclk.rresp = next_status_tclk_comb;

  localparam int unsigned RspFifoWidth = $bits(series_read_rsp_t);

  logic rsp_fifo_clr_tclk;

  assign rsp_fifo_clr_tclk =
        (security_disable_i && (axi_state_q_tclk == AXI_IDLE)) ||
        ctrl_flush_pulse_tclk;

  prim_fifo_sync #(
    .Width            (RspFifoWidth),
    .Depth            (SERIES_RSP_FIFO_SIZE),
    .Pass             (1'b0),
    .OutputZeroIfEmpty(1'b0),
    .NeverClears      (1'b0),
    .Secure           (1'b0)
  ) u_series_rsp_fifo (
    .clk_i   (i_tck),
    .rst_ni  (i_trstn),
    .clr_i   (rsp_fifo_clr_tclk),
    .wvalid_i(series_rsp_fifo_push_tclk),
    .wready_o(/* unused */),
    .wdata_i (series_rsp_fifo_din_tclk),
    .rvalid_o(/* unused */),
    .rready_i(series_rsp_fifo_pop_tclk),
    .rdata_o (series_rsp_fifo_dout_tclk),
    .full_o  (series_rsp_fifo_full_tclk),
    .depth_o (series_rsp_fifo_count_tclk),
    .err_o   ()
  );

  assign series_rsp_fifo_empty_tclk = (series_rsp_fifo_count_tclk == '0);

  //--------------------------------------------------------------------------
  // AXI FSM State Register and Current Transaction Parameter Latch (TCK)
  //--------------------------------------------------------------------------
  always_ff @(posedge i_tck or negedge i_trstn) begin
    if (!i_trstn) begin
      axi_state_q_tclk                                 <= AXI_IDLE;
      current_tx_is_series_read_tclk                   <= 1'b0;
      current_tx_is_from_single_buffer_tclk            <= 1'b0;
      current_is_series_data_with_error_status_op_tclk <= 1'b0;
      current_op_tclk                                  <= JTAG_OP_NOP;
      current_addr_tclk                                <= '0;
      current_data_tclk                                <= '0;
      current_jtag_size_tclk                           <= '0;
      current_custom_wstrb_tclk                        <= '0;
      current_use_custom_wstrb_tclk                    <= 1'b0;
      current_incr_series_addr_tclk                    <= 1'b0;
      current_tx_stale_tclk                            <= 1'b0;
    end else begin
      axi_state_q_tclk <= axi_state_d_tclk;

      // A new CTRL programming arriving while the FSM is mid-flight on
      // a series read marks that in-flight transaction as stale. Its
      // response will complete on AXI but will not enter the freshly
      // flushed rsp-FIFO. The flag self-clears when the FSM returns to
      // IDLE.
      if (ctrl_flush_pulse_tclk &&
                (axi_state_q_tclk != AXI_IDLE) &&
                current_tx_is_series_read_tclk &&
                !current_is_series_data_with_error_status_op_tclk) begin
        current_tx_stale_tclk <= 1'b1;
      end else if (axi_state_d_tclk == AXI_IDLE && axi_state_q_tclk != AXI_IDLE) begin
        current_tx_stale_tclk <= 1'b0;
      end

      if (axi_state_q_tclk == AXI_IDLE && axi_state_d_tclk != AXI_IDLE) begin
        current_tx_is_from_single_buffer_tclk <= single_tx_req_valid_tclk;
        if (single_tx_req_valid_tclk) begin
          current_tx_is_series_read_tclk                   <= 1'b0;
          current_is_series_data_with_error_status_op_tclk <= 1'b0;
          current_op_tclk                                  <= single_tx_op_tclk;
          current_addr_tclk                                <= single_tx_addr_tclk;
          current_data_tclk                                <= single_tx_data_tclk;
          current_jtag_size_tclk                           <= single_tx_axi_size_tclk;
          current_custom_wstrb_tclk                        <= single_tx_wstrb_tclk;
          current_use_custom_wstrb_tclk                    <= 1'b1;
          current_incr_series_addr_tclk                    <= 1'b0;
        end else begin
          current_tx_is_series_read_tclk                   <=
                        (series_request_fifo_dout_tclk.op == JTAG_OP_READ);
          current_is_series_data_with_error_status_op_tclk <=
                        series_request_fifo_dout_tclk.is_series_data_with_error_status_op;
          current_op_tclk                                  <= series_request_fifo_dout_tclk.op;
          current_addr_tclk                                <= series_request_fifo_dout_tclk.addr;
          current_data_tclk                                <= series_request_fifo_dout_tclk.data;
          current_jtag_size_tclk                           <= series_request_fifo_dout_tclk.jtag_size;
          current_custom_wstrb_tclk                        <= '0;
          current_use_custom_wstrb_tclk                    <= 1'b0;
          current_incr_series_addr_tclk                    <= series_request_fifo_dout_tclk.increment_addr;
        end
      end else if (axi_state_d_tclk == AXI_IDLE && axi_state_q_tclk != AXI_IDLE) begin
        current_tx_is_series_read_tclk                   <= 1'b0;
        current_tx_is_from_single_buffer_tclk            <= 1'b0;
        current_is_series_data_with_error_status_op_tclk <= 1'b0;
        current_op_tclk                                  <= JTAG_OP_NOP;
        current_addr_tclk                                <= '0;
        current_data_tclk                                <= '0;
        current_jtag_size_tclk                           <= '0;
        current_custom_wstrb_tclk                        <= '0;
        current_use_custom_wstrb_tclk                    <= 1'b0;
        current_incr_series_addr_tclk                    <= 1'b0;
      end
    end
  end

  assign axi_transaction_in_progress_tclk = (axi_state_q_tclk != AXI_IDLE);

  //--------------------------------------------------------------------------
  // AXI FSM Next-State Logic and Internal src_req Channel Drivers (TCK)
  //--------------------------------------------------------------------------
  always_comb begin
    axi_state_d_tclk             = axi_state_q_tclk;
    series_request_fifo_pop_tclk = 1'b0;

    src_req.aw_valid = 1'b0;
    src_req.w_valid  = 1'b0;
    src_req.b_ready  = 1'b0;
    src_req.ar_valid = 1'b0;
    src_req.r_ready  = 1'b0;

    fsm_updates_bresp_status_tclk_comb = 1'b0;
    fsm_updates_rdata_status_tclk_comb = 1'b0;
    next_status_tclk_comb              = last_single_op_status_tclk;
    next_read_data_tclk_comb           = last_read_data_tclk;

    case (axi_state_q_tclk)
      AXI_IDLE: begin
        if (security_disable_i) begin
          axi_state_d_tclk = AXI_IDLE;
        end else if (single_tx_req_valid_tclk) begin
          if (single_tx_op_tclk == JTAG_OP_WRITE) begin
            axi_state_d_tclk = AXI_SEND_ADDR_W;
          end else if (single_tx_op_tclk == JTAG_OP_READ) begin
            axi_state_d_tclk = AXI_SEND_ADDR_R;
          end else begin
            axi_state_d_tclk = AXI_IDLE;
          end
        end else if (!series_request_fifo_empty_tclk) begin
          if (series_request_fifo_dout_tclk.op == JTAG_OP_READ) begin
            if (series_reads_in_flight_tclk < (series_ctrl_pipeline_depth_tclk_r + 1)) begin
              series_request_fifo_pop_tclk = 1'b1;
              axi_state_d_tclk             = AXI_SEND_ADDR_R;
            end
          end else begin
            series_request_fifo_pop_tclk = 1'b1;
            axi_state_d_tclk             = AXI_SEND_ADDR_W;
          end
        end
      end

      AXI_SEND_ADDR_W: begin
        src_req.aw_valid = 1'b1;
        if (src_resp.aw_ready) begin
          if (src_resp.w_ready) begin
            src_req.w_valid  = 1'b1;
            axi_state_d_tclk = AXI_WAIT_BRESP;
          end else begin
            axi_state_d_tclk = AXI_SEND_DATA_W;
          end
        end
      end

      AXI_SEND_DATA_W: begin
        src_req.w_valid = 1'b1;
        if (src_resp.w_ready) begin
          axi_state_d_tclk = AXI_WAIT_BRESP;
        end
      end

      AXI_WAIT_BRESP: begin
        src_req.b_ready = 1'b1;
        if (src_resp.b_valid) begin
          fsm_updates_bresp_status_tclk_comb = 1'b1;
          next_status_tclk_comb =
                        (src_resp.b.resp == 2'b00) ? CAPTURE_STATUS_SUCCESS :
                        (src_resp.b.resp == 2'b10) ? CAPTURE_STATUS_SLVERR  :
                        (src_resp.b.resp == 2'b11) ? CAPTURE_STATUS_DECERR  :
                                                     CAPTURE_STATUS_SLVERR;
          axi_state_d_tclk = AXI_UPDATE_STATUS;
        end
      end

      AXI_SEND_ADDR_R: begin
        src_req.ar_valid = 1'b1;
        if (src_resp.ar_ready) begin
          axi_state_d_tclk = AXI_WAIT_RDATA;
        end
      end

      AXI_WAIT_RDATA: begin
        // Plain series reads must have room in the response FIFO before
        // accepting the R beat; otherwise captured data would be lost.
        // Single-buffer and errstat reads write the latched "last read"
        // register directly and are always ready.
        if (current_tx_is_series_read_tclk &&
                    !current_is_series_data_with_error_status_op_tclk) begin
          src_req.r_ready = !series_rsp_fifo_full_tclk;
        end else begin
          src_req.r_ready = 1'b1;
        end

        if (src_resp.r_valid && src_req.r_ready) begin
          fsm_updates_rdata_status_tclk_comb = 1'b1;
          next_read_data_tclk_comb = current_tx_is_from_single_buffer_tclk
                        ? src_resp.r.data
                        : series_lane_rdata(src_resp.r.data, current_addr_tclk);
          next_status_tclk_comb =
                        (src_resp.r.resp == 2'b00) ? CAPTURE_STATUS_SUCCESS :
                        (src_resp.r.resp == 2'b10) ? CAPTURE_STATUS_SLVERR  :
                        (src_resp.r.resp == 2'b11) ? CAPTURE_STATUS_DECERR  :
                                                     CAPTURE_STATUS_SLVERR;
          if (src_resp.r.last) begin
            axi_state_d_tclk = AXI_UPDATE_STATUS;
          end
        end
      end

      AXI_UPDATE_STATUS: begin
        axi_state_d_tclk = AXI_IDLE;
      end

      default: axi_state_d_tclk = AXI_IDLE;
    endcase
  end

  //--------------------------------------------------------------------------
  // src_req AW/W/AR channel struct population (constant fields + dynamic)
  //--------------------------------------------------------------------------
  always_comb begin
    src_req.aw        = '0;
    src_req.aw.id     = ID_WIDTH'(0);
    src_req.aw.addr   = current_addr_tclk;
    src_req.aw.len    = AXI_LEN_SINGLE;
    src_req.aw.size   = current_axi_axsize_tclk;
    src_req.aw.burst  = AXI_BURST_INCR;
    src_req.aw.lock   = 1'b0;
    src_req.aw.cache  = AXI_CACHE_DEFAULT;
    src_req.aw.prot   = AXI_PROT_DEFAULT;
    src_req.aw.qos    = 4'b0;
    src_req.aw.region = 4'b0;
    src_req.aw.atop   = '0;
    src_req.aw.user   = USER_WIDTH'(0);

    src_req.w      = '0;
    src_req.w.data = current_use_custom_wstrb_tclk
            ? current_data_tclk
            : series_lane_wdata(current_data_tclk, current_addr_tclk);
    src_req.w.strb = current_wstrb_tclk;
    src_req.w.last = 1'b1;
    src_req.w.user = USER_WIDTH'(0);

    src_req.ar        = '0;
    src_req.ar.id     = ID_WIDTH'(0);
    src_req.ar.addr   = current_addr_tclk;
    src_req.ar.len    = AXI_LEN_SINGLE;
    src_req.ar.size   = current_axi_axsize_tclk;
    src_req.ar.burst  = AXI_BURST_INCR;
    src_req.ar.lock   = 1'b0;
    src_req.ar.cache  = AXI_CACHE_DEFAULT;
    src_req.ar.prot   = AXI_PROT_DEFAULT;
    src_req.ar.qos    = 4'b0;
    src_req.ar.region = 4'b0;
    src_req.ar.user   = USER_WIDTH'(0);
  end

  // Derive current_axi_axsize from the scanned jtag size field
  generate
    if (SCAN_CHAIN_SIZE_FIELD_WIDTH == 1) begin : gen_axsize_1bit
      always_comb begin
        current_axi_axsize_tclk = {2'b00, current_jtag_size_tclk[0]};
      end
    end else if (SCAN_CHAIN_SIZE_FIELD_WIDTH == 2) begin : gen_axsize_2bit
      always_comb begin
        current_axi_axsize_tclk = {1'b0, current_jtag_size_tclk[1:0]};
      end
    end else if (SCAN_CHAIN_SIZE_FIELD_WIDTH == 3) begin : gen_axsize_3bit
      always_comb begin
        logic [2:0] temp_axsize_val;
        temp_axsize_val = current_jtag_size_tclk[2:0];
        if (temp_axsize_val[2]) begin
          current_axi_axsize_tclk = 3'b011;
        end else begin
          current_axi_axsize_tclk = temp_axsize_val;
        end
      end
    end else begin : gen_axsize_default
      always_comb begin
        current_axi_axsize_tclk = 3'b000;
      end
    end
  endgenerate

  // current_wstrb: custom mask for single-buffer writes, lane-aligned
  // generated mask for series writes.
  always_comb begin
    current_wstrb_tclk = '0;
    if (current_op_tclk == JTAG_OP_WRITE) begin
      if (current_use_custom_wstrb_tclk) begin
        current_wstrb_tclk = current_custom_wstrb_tclk;
      end else begin
        current_wstrb_tclk = series_lane_wstrb(current_addr_tclk, current_axi_axsize_tclk);
      end
    end
  end

  //--------------------------------------------------------------------------
  // JTAG Update Dispatch, Series Control State, and Status Updates (TCK)
  //--------------------------------------------------------------------------
  logic                                   single_tx_req_valid_tclk_d;
  logic [1:0]                             single_tx_op_tclk_d;
  logic [ADDR_WIDTH-1:0]                  single_tx_addr_tclk_d;
  logic [DATA_WIDTH-1:0]                  single_tx_data_tclk_d;
  logic [SCAN_CHAIN_SIZE_FIELD_WIDTH-1:0] single_tx_axi_size_tclk_d;
  logic [WSTRB_FIELD_WIDTH-1:0]           single_tx_wstrb_tclk_d;

  logic [AXISERIESCTRL_SIZE_BITS-1:0] series_ctrl_size_tclk_r_d;
  logic [AXISERIESCTRL_PD_BITS-1:0]   series_ctrl_pipeline_depth_tclk_r_d;
  logic [ADDR_WIDTH-1:0]              series_ctrl_address_tclk_r_d;
  logic [1:0]                         series_ctrl_op_mode_tclk_r_d;

  logic                  single_op_pending_tclk_d;
  logic                  series_errstat_pending_tclk_d;
  logic [1:0]            last_single_op_status_tclk_d;
  logic [DATA_WIDTH-1:0] last_read_data_tclk_d;
  logic                  last_single_op_was_read_tclk_d;
  logic [1:0]            sticky_axi_status_tclk_d;
  logic                  sticky_axi_status_full_tclk_d;

  logic [PIPELINE_DEPTH_FIELD_BITS-1:0] series_read_preload_count_tclk_d;
  logic [$clog2(FIFO_DEPTH+2)-1:0]      plain_reads_pending_tclk_d;
  logic [$clog2(FIFO_DEPTH+2)-1:0]      series_reads_in_flight_tclk_d;
  logic [$clog2(FIFO_DEPTH+2)-1:0]      series_reads_pushed_tclk_d;

  logic                                 series_request_fifo_push_tclk_d;
  series_request_fifo_entry_t           series_request_fifo_din_tclk_d;

  always_comb begin
    single_tx_req_valid_tclk_d          = single_tx_req_valid_tclk;
    single_tx_op_tclk_d                 = single_tx_op_tclk;
    single_tx_addr_tclk_d               = single_tx_addr_tclk;
    single_tx_data_tclk_d               = single_tx_data_tclk;
    single_tx_axi_size_tclk_d           = single_tx_axi_size_tclk;
    single_tx_wstrb_tclk_d              = single_tx_wstrb_tclk;
    series_ctrl_size_tclk_r_d           = series_ctrl_size_tclk_r;
    series_ctrl_pipeline_depth_tclk_r_d = series_ctrl_pipeline_depth_tclk_r;
    series_ctrl_address_tclk_r_d        = series_ctrl_address_tclk_r;
    series_ctrl_op_mode_tclk_r_d        = series_ctrl_op_mode_tclk_r;
    single_op_pending_tclk_d            = single_op_pending_tclk;
    series_errstat_pending_tclk_d       = series_errstat_pending_tclk;
    last_single_op_status_tclk_d        = last_single_op_status_tclk;
    last_read_data_tclk_d               = last_read_data_tclk;
    last_single_op_was_read_tclk_d      = last_single_op_was_read_tclk;
    sticky_axi_status_tclk_d            = sticky_axi_status_tclk;
    sticky_axi_status_full_tclk_d       = sticky_axi_status_full_tclk;
    series_read_preload_count_tclk_d    = series_read_preload_count_tclk;
    plain_reads_pending_tclk_d          = plain_reads_pending_tclk;
    series_reads_in_flight_tclk_d       = series_reads_in_flight_tclk;
    series_reads_pushed_tclk_d          = series_reads_pushed_tclk;
    series_request_fifo_push_tclk_d     = 1'b0;
    series_request_fifo_din_tclk_d      = series_request_fifo_din_tclk;

    // A new CTRL programming flushes the series-pipeline accounting.
    // Any in-flight AXI read is allowed to complete on the bus (its
    // response is dropped via `current_tx_stale_tclk`); the cleared
    // counters cannot underflow because the decrement paths below
    // are guarded by `> 0` checks.
    if ((security_disable_i && (axi_state_q_tclk == AXI_IDLE)) || ctrl_flush_pulse_tclk) begin
      plain_reads_pending_tclk_d    = '0;
      series_reads_in_flight_tclk_d = '0;
      series_reads_pushed_tclk_d    = '0;
    end

    // `single_tx_req_valid_tclk` is only cleared by security-disable, not by
    // ctrl-flush (a fresh CTRL programming can leave a buffered single-op
    // pending until the FSM consumes it).
    if (security_disable_i && (axi_state_q_tclk == AXI_IDLE)) begin
      single_tx_req_valid_tclk_d = 1'b0;
    end

    // The FSM is about to consume the single-op buffer; drop the valid
    // flag in the same TCK edge so a new JTAG update can land next.
    if (axi_state_q_tclk == AXI_IDLE && axi_state_d_tclk != AXI_IDLE &&
            single_tx_req_valid_tclk) begin
      single_tx_req_valid_tclk_d     = 1'b0;
      last_single_op_was_read_tclk_d = (single_tx_op_tclk == JTAG_OP_READ);
    end

    // Track series reads in flight on AXI (used for pipeline_depth gate).
    if (axi_state_q_tclk == AXI_SEND_ADDR_R && src_req.ar_valid && src_resp.ar_ready &&
            current_tx_is_series_read_tclk) begin
      series_reads_in_flight_tclk_d = series_reads_in_flight_tclk + 1'b1;
    end else if (axi_state_q_tclk == AXI_WAIT_RDATA && src_resp.r_valid && src_req.r_ready &&
                     src_resp.r.last && current_tx_is_series_read_tclk) begin
      if (series_reads_in_flight_tclk > 0) begin
        series_reads_in_flight_tclk_d = series_reads_in_flight_tclk - 1'b1;
      end
    end

    // Process JTAG update: latch single-op buffer, update series-control
    // state, or push a series data entry into the request FIFO.
    if (i_update_en && !security_disable_i) begin
      if (i_select_AXISingleOp) begin
        automatic logic [1:0] single_op_val;
        single_op_val = update_register_q_tclk[AXISINGLEOP_OP_HIGH:AXISINGLEOP_OP_LOW];
        // READ/WRITE while a beat is in flight is a rejected operation.
        // NOP (and reserved) Update-DR is a status poll and must not set
        // sticky_full or clear pending.
        if (single_op_val == JTAG_OP_READ || single_op_val == JTAG_OP_WRITE) begin
          if (!(axi_transaction_in_progress_tclk || single_tx_req_valid_tclk)) begin
            single_tx_req_valid_tclk_d     = 1'b1;
            single_tx_op_tclk_d            = single_op_val;
            single_tx_addr_tclk_d          = update_register_q_tclk[AXISINGLEOP_ADDR_HIGH : AXISINGLEOP_ADDR_LOW];
            single_tx_data_tclk_d          = update_register_q_tclk[AXISINGLEOP_DATA_HIGH : AXISINGLEOP_DATA_LOW];
            single_tx_axi_size_tclk_d      = update_register_q_tclk[AXISINGLEOP_SIZE_HIGH : AXISINGLEOP_SIZE_LOW];
            single_tx_wstrb_tclk_d         = update_register_q_tclk[AXISINGLEOP_WSTRB_HIGH: AXISINGLEOP_WSTRB_LOW];
            single_op_pending_tclk_d       = 1'b1;
            last_single_op_was_read_tclk_d = (single_op_val == JTAG_OP_READ);
          end else begin
            sticky_axi_status_full_tclk_d = 1'b1;
            last_single_op_status_tclk_d  = CAPTURE_STATUS_BUSY_OR_FULL;
            single_op_pending_tclk_d      = 1'b0;
          end
        end
      end else if (i_select_AXISeriesCtrl) begin
        automatic logic [1:0] op_val;
        automatic logic [AXISERIESCTRL_PD_BITS-1:0] pd_val;
        op_val = update_register_q_tclk[AXISERIESCTRL_OP_HIGH:AXISERIESCTRL_OP_LOW];
        pd_val = (update_register_q_tclk[AXISERIESCTRL_PD_HIGH:AXISERIESCTRL_PD_LOW] > FIFO_DEPTH) ?
                         FIFO_DEPTH[PIPELINE_DEPTH_FIELD_BITS-1:0] :
                         update_register_q_tclk[AXISERIESCTRL_PD_HIGH:AXISERIESCTRL_PD_LOW];

        // Only reprogram series CTRL state (including the read
        // preload counter) on a real op. A NO_OP update (issued by
        // CTRL TDR read-backs) must not clobber preload/address/
        // pipeline-depth state accumulated by the in-flight series
        // operation.
        if (op_val != JTAG_OP_NOP) begin
          series_ctrl_size_tclk_r_d           = update_register_q_tclk[AXISERIESCTRL_SIZE_HIGH:AXISERIESCTRL_SIZE_LOW];
          series_ctrl_pipeline_depth_tclk_r_d = pd_val;
          series_ctrl_address_tclk_r_d        = update_register_q_tclk[AXISERIESCTRL_ADDR_HIGH:AXISERIESCTRL_ADDR_LOW];
          series_ctrl_op_mode_tclk_r_d        = op_val;
          if (op_val == JTAG_OP_READ) begin
            series_read_preload_count_tclk_d = pd_val;
          end else begin
            series_read_preload_count_tclk_d = '0;
          end
          // `series_reads_pushed_tclk` and the other pipeline
          // accounting counters are flushed centrally via
          // `ctrl_flush_pulse_tclk`; nothing extra needed here.
        end
        if (update_register_q_tclk[AXISERIESCTRL_RESET_HIGH]) begin
          sticky_axi_status_tclk_d      = CAPTURE_STATUS_SUCCESS;
          sticky_axi_status_full_tclk_d = 1'b0;
        end
      end else if (i_select_AXISeriesDataIncr || i_select_AXISeriesDataNoIncr ||
                         i_select_AXISeriesDataWithErrorStatus) begin
        automatic logic [$clog2(SHARED_SR_LEN+1)-1:0] current_mapped_data_len_local;
        automatic int num_bytes_to_copy;
        automatic logic [DATA_WIDTH-1:0] data_val;
        automatic logic incr_addr_bit;
        automatic logic can_accept;
        automatic logic budget_ok;
        automatic logic is_plain_read;

        data_val = update_register_q_tclk[DATA_WIDTH-1:0];
        incr_addr_bit = i_select_AXISeriesDataIncr;

        if (i_select_AXISeriesDataWithErrorStatus) begin
          current_mapped_data_len_local = size_to_bits(3'(latched_series_size_for_len_tclk));
          if (current_mapped_data_len_local > DATA_WIDTH)
            current_mapped_data_len_local = DATA_WIDTH;
          num_bytes_to_copy = int'(current_mapped_data_len_local) >> 3; // bits-to-bytes: divide by 8

          data_val = '0;
          for (int byte_idx = 0; byte_idx < DATA_WIDTH / 8; byte_idx++) begin
            if (byte_idx < num_bytes_to_copy) begin
              data_val[byte_idx*8+:8] = update_register_q_tclk[byte_idx*8+:8];
            end
          end
          if (current_mapped_data_len_local < SHARED_SR_LEN) begin
            incr_addr_bit = update_register_q_tclk[current_mapped_data_len_local];
          end else begin
            incr_addr_bit = 1'b0;
          end
        end

        is_plain_read = (series_ctrl_op_mode_tclk_r == JTAG_OP_READ) &&
                                !i_select_AXISeriesDataWithErrorStatus;

        if (series_ctrl_op_mode_tclk_r == JTAG_OP_READ) begin
          // Two distinct gates for reads:
          //   `can_accept` = backpressure-class admit gate: FIFO
          //                  not full and AXI in-flight bound
          //                  not exceeded. A failure here is
          //                  reported as backpressure to the
          //                  host via sticky_full.
          //   `budget_ok`  = informational per-CTRL-programming
          //                  push budget. The standard JTAG
          //                  host pattern issues 1 INCR-Read
          //                  scan + N readback scans, which
          //                  would otherwise enqueue (1 + N)
          //                  requests but only consume 1 rsp-
          //                  FIFO entry per programming and
          //                  leak stale data forward. We
          //                  silently drop pushes past the
          //                  budget without raising sticky_full
          //                  since this is the host's expected
          //                  pattern, not a true backpressure
          //                  condition.
          can_accept = !series_request_fifo_full_tclk &&
                                 (series_reads_in_flight_tclk < (series_ctrl_pipeline_depth_tclk_r + 1));
          budget_ok  = (series_reads_pushed_tclk    < (series_ctrl_pipeline_depth_tclk_r + 1));
        end else begin
          can_accept = !series_request_fifo_full_tclk;
          budget_ok  = 1'b1;
        end

        if (can_accept && budget_ok) begin
          series_request_fifo_push_tclk_d                                = 1'b1;
          series_request_fifo_din_tclk_d.addr                            = series_ctrl_address_tclk_r;
          series_request_fifo_din_tclk_d.op                              = series_ctrl_op_mode_tclk_r;
          series_request_fifo_din_tclk_d.jtag_size                       = series_ctrl_size_tclk_r;
          series_request_fifo_din_tclk_d.is_series_data_with_error_status_op =
                        i_select_AXISeriesDataWithErrorStatus;
          series_request_fifo_din_tclk_d.data                            = data_val;
          series_request_fifo_din_tclk_d.increment_addr                  = incr_addr_bit;

          if (is_plain_read) begin
            plain_reads_pending_tclk_d = plain_reads_pending_tclk + 1'b1;
            series_reads_pushed_tclk_d = series_reads_pushed_tclk + 1'b1;
          end

          if (i_select_AXISeriesDataWithErrorStatus) begin
            series_errstat_pending_tclk_d = 1'b1;
          end
        end else if (!can_accept) begin
          // True backpressure: FIFO full or AXI in-flight bound
          // hit. Surface to host via sticky_full. Errstat
          // captures also record BUSY_OR_FULL on the single-op
          // status path.
          sticky_axi_status_full_tclk_d = 1'b1;
          if (i_select_AXISeriesDataWithErrorStatus) begin
            last_single_op_status_tclk_d  = CAPTURE_STATUS_BUSY_OR_FULL;
            series_errstat_pending_tclk_d = 1'b0;
          end
        end
        // else (!budget_ok): silent drop, see comment above.
      end
    end

    // Read pipeline preload decrement on capture (TCK-local)
    if (i_capture_en && (i_select_AXISeriesDataIncr || i_select_AXISeriesDataNoIncr) &&
            (series_ctrl_op_mode_tclk_r == JTAG_OP_READ)) begin
      if (series_read_preload_count_tclk > 0) begin
        series_read_preload_count_tclk_d = series_read_preload_count_tclk - 1'b1;
      end
    end

    // Series address auto-increment on transaction completion for
    // increment-enabled series data entries.
    if (axi_state_q_tclk == AXI_UPDATE_STATUS &&
            current_incr_series_addr_tclk &&
            !current_tx_is_from_single_buffer_tclk) begin
      automatic logic [7:0]          num_bytes_to_increment;
      automatic logic [ADDR_WIDTH:0] next_series_addr_ext;
      num_bytes_to_increment = 8'(1 << current_axi_axsize_tclk);
      next_series_addr_ext   = {1'b0, series_ctrl_address_tclk_r}
                                   + ADDR_WIDTH'(num_bytes_to_increment);
      // Address wraps at the top of the configured ADDR_WIDTH; the JTAG host
      // is responsible for staying within an addressable AXI region.
      series_ctrl_address_tclk_r_d = next_series_addr_ext[ADDR_WIDTH-1:0];
    end

    // Decrement plain-read pending counter when the plain series read
    // completes on AXI.
    if (axi_state_q_tclk == AXI_WAIT_RDATA && src_resp.r_valid && src_req.r_ready &&
            src_resp.r.last &&
            current_tx_is_series_read_tclk &&
            !current_is_series_data_with_error_status_op_tclk) begin
      if (plain_reads_pending_tclk > 0) begin
        plain_reads_pending_tclk_d = plain_reads_pending_tclk - 1'b1;
      end
    end

    // FSM completion status updates (write response path).
    if (fsm_updates_bresp_status_tclk_comb) begin
      sticky_axi_status_tclk_d = next_status_tclk_comb;
      if (current_tx_is_from_single_buffer_tclk ||
                current_is_series_data_with_error_status_op_tclk) begin
        last_single_op_status_tclk_d = next_status_tclk_comb;
      end
      if (current_tx_is_from_single_buffer_tclk) begin
        single_op_pending_tclk_d = 1'b0;
      end
      if (current_is_series_data_with_error_status_op_tclk) begin
        series_errstat_pending_tclk_d = 1'b0;
      end
    end

    // FSM completion status updates (read response path).
    if (fsm_updates_rdata_status_tclk_comb) begin
      sticky_axi_status_tclk_d = next_status_tclk_comb;
      if ((current_tx_is_from_single_buffer_tclk && !current_tx_is_series_read_tclk) ||
                current_is_series_data_with_error_status_op_tclk) begin
        last_single_op_status_tclk_d = next_status_tclk_comb;
        last_read_data_tclk_d        = next_read_data_tclk_comb;
      end
      if (current_tx_is_from_single_buffer_tclk) begin
        single_op_pending_tclk_d = 1'b0;
      end
      if (current_is_series_data_with_error_status_op_tclk) begin
        series_errstat_pending_tclk_d = 1'b0;
      end
    end
  end

  always_ff @(posedge i_tck or negedge i_trstn) begin
    if (!i_trstn) begin
      single_tx_req_valid_tclk          <= 1'b0;
      single_tx_op_tclk                 <= JTAG_OP_NOP;
      single_tx_addr_tclk               <= '0;
      single_tx_data_tclk               <= '0;
      single_tx_axi_size_tclk           <= '0;
      single_tx_wstrb_tclk              <= '0;

      series_ctrl_size_tclk_r           <= '0;
      series_ctrl_pipeline_depth_tclk_r <= '0;
      series_ctrl_address_tclk_r        <= '0;
      series_ctrl_op_mode_tclk_r        <= JTAG_OP_NOP;

      single_op_pending_tclk            <= 1'b0;
      series_errstat_pending_tclk       <= 1'b0;
      last_single_op_status_tclk        <= CAPTURE_STATUS_SUCCESS;
      last_read_data_tclk               <= '0;
      last_single_op_was_read_tclk      <= 1'b0;
      sticky_axi_status_tclk            <= CAPTURE_STATUS_SUCCESS;
      sticky_axi_status_full_tclk       <= 1'b0;

      series_read_preload_count_tclk    <= '0;
      plain_reads_pending_tclk          <= '0;
      series_reads_in_flight_tclk       <= '0;
      series_reads_pushed_tclk          <= '0;

      series_request_fifo_push_tclk     <= 1'b0;
      series_request_fifo_din_tclk      <= '{default:'0};
    end else begin
      single_tx_req_valid_tclk          <= single_tx_req_valid_tclk_d;
      single_tx_op_tclk                 <= single_tx_op_tclk_d;
      single_tx_addr_tclk               <= single_tx_addr_tclk_d;
      single_tx_data_tclk               <= single_tx_data_tclk_d;
      single_tx_axi_size_tclk           <= single_tx_axi_size_tclk_d;
      single_tx_wstrb_tclk              <= single_tx_wstrb_tclk_d;

      series_ctrl_size_tclk_r           <= series_ctrl_size_tclk_r_d;
      series_ctrl_pipeline_depth_tclk_r <= series_ctrl_pipeline_depth_tclk_r_d;
      series_ctrl_address_tclk_r        <= series_ctrl_address_tclk_r_d;
      series_ctrl_op_mode_tclk_r        <= series_ctrl_op_mode_tclk_r_d;

      single_op_pending_tclk            <= single_op_pending_tclk_d;
      series_errstat_pending_tclk       <= series_errstat_pending_tclk_d;
      last_single_op_status_tclk        <= last_single_op_status_tclk_d;
      last_read_data_tclk               <= last_read_data_tclk_d;
      last_single_op_was_read_tclk      <= last_single_op_was_read_tclk_d;
      sticky_axi_status_tclk            <= sticky_axi_status_tclk_d;
      sticky_axi_status_full_tclk       <= sticky_axi_status_full_tclk_d;

      series_read_preload_count_tclk    <= series_read_preload_count_tclk_d;
      plain_reads_pending_tclk          <= plain_reads_pending_tclk_d;
      series_reads_in_flight_tclk       <= series_reads_in_flight_tclk_d;
      series_reads_pushed_tclk          <= series_reads_pushed_tclk_d;

      series_request_fifo_push_tclk     <= series_request_fifo_push_tclk_d;
      series_request_fifo_din_tclk      <= series_request_fifo_din_tclk_d;
    end
  end

  //--------------------------------------------------------------------------
  // JTAG Capture Data Preparation (TCK Domain)
  //--------------------------------------------------------------------------
  always_comb begin
    capture_data_tclk       = '0;
    series_rsp_fifo_pop_tclk = 1'b0;

    if (i_select_AXISingleOp) begin
      if (single_op_pending_tclk) begin
        capture_data_tclk[AXISINGLEOP_OP_HIGH:AXISINGLEOP_OP_LOW] = CAPTURE_STATUS_BUSY_OR_FULL;
      end else begin
        capture_data_tclk[AXISINGLEOP_OP_HIGH:AXISINGLEOP_OP_LOW] = last_single_op_status_tclk;
      end

      if (last_single_op_was_read_tclk) begin
        if (single_op_pending_tclk) begin
          capture_data_tclk[AXISINGLEOP_DATA_HIGH:AXISINGLEOP_DATA_LOW] = RDATA_PENDING_VALUE_CONST;
        end else begin
          capture_data_tclk[AXISINGLEOP_DATA_HIGH:AXISINGLEOP_DATA_LOW] = last_read_data_tclk;
        end
      end else begin
        capture_data_tclk[AXISINGLEOP_DATA_HIGH:AXISINGLEOP_DATA_LOW] = single_op_data_tclk;
      end

      capture_data_tclk[AXISINGLEOP_SIZE_HIGH:AXISINGLEOP_SIZE_LOW]   = single_op_size_tclk;
      capture_data_tclk[AXISINGLEOP_WSTRB_HIGH:AXISINGLEOP_WSTRB_LOW] = single_op_wstrb_tclk;
      capture_data_tclk[AXISINGLEOP_ADDR_HIGH:AXISINGLEOP_ADDR_LOW]   = single_op_addr_tclk;

    end else if (i_select_AXISeriesCtrl) begin
      // Address capture must present the post-increment value when the
      // FSM is completing or has just completed a series write/read with
      // increment on this same TCK edge. Without this, a Capture-DR that
      // coincides with the FSM's `AXI_UPDATE_STATUS` edge (or the beat
      // that generates BRESP/RDATA-last) samples `series_ctrl_address_tclk_r`
      // combinationally before its non-blocking increment commits, so
      // the host observes the pre-increment address.
      automatic logic [ADDR_WIDTH-1:0] visible_addr;
      automatic logic                  completion_edge;
      completion_edge =
                current_incr_series_addr_tclk && !current_tx_is_from_single_buffer_tclk &&
                ((axi_state_q_tclk == AXI_UPDATE_STATUS) ||
                 (axi_state_q_tclk == AXI_WAIT_BRESP && src_resp.b_valid && src_req.b_ready) ||
                 (axi_state_q_tclk == AXI_WAIT_RDATA && src_resp.r_valid && src_req.r_ready &&
                  src_resp.r.last));
      if (completion_edge) begin
        visible_addr = series_ctrl_address_tclk_r + (1 << current_axi_axsize_tclk);
      end else begin
        visible_addr = series_ctrl_address_tclk_r;
      end

      if (sticky_axi_status_full_tclk) begin
        capture_data_tclk[AXISERIESCTRL_OP_HIGH:AXISERIESCTRL_OP_LOW] = CAPTURE_STATUS_BUSY_OR_FULL;
      end else begin
        capture_data_tclk[AXISERIESCTRL_OP_HIGH:AXISERIESCTRL_OP_LOW] = sticky_axi_status_tclk;
      end
      capture_data_tclk[AXISERIESCTRL_SIZE_HIGH:AXISERIESCTRL_SIZE_LOW] = series_ctrl_size_tclk_r;
      capture_data_tclk[AXISERIESCTRL_PD_HIGH:AXISERIESCTRL_PD_LOW]     = series_ctrl_pipeline_depth_tclk_r;
      capture_data_tclk[AXISERIESCTRL_ADDR_HIGH:AXISERIESCTRL_ADDR_LOW] = visible_addr;
      capture_data_tclk[AXISERIESCTRL_RESET_HIGH] = 1'b0;

    end else if (i_select_AXISeriesDataIncr || i_select_AXISeriesDataNoIncr) begin
      automatic int mapped_len_for_capture_local;
      automatic int num_bytes_to_copy;

      mapped_len_for_capture_local = size_to_bits(3'(latched_series_size_for_len_tclk));
      if (mapped_len_for_capture_local > DATA_WIDTH) mapped_len_for_capture_local = DATA_WIDTH;
      num_bytes_to_copy = mapped_len_for_capture_local >> 3;  // bits-to-bytes: divide by 8

      if (series_ctrl_op_mode_tclk_r == JTAG_OP_READ) begin
        for (int byte_idx = 0; byte_idx < DATA_WIDTH / 8; byte_idx++) begin
          if (byte_idx < num_bytes_to_copy) begin
            if (series_read_preload_count_tclk > 0) begin
              capture_data_tclk[byte_idx*8+:8] = RDATA_PENDING_VALUE_CONST[byte_idx*8+:8];
            end else if (!series_rsp_fifo_empty_tclk) begin
              capture_data_tclk[byte_idx*8+:8] = series_rsp_fifo_dout_tclk.rdata[byte_idx*8+:8];
            end else if (plain_reads_pending_tclk > 0) begin
              capture_data_tclk[byte_idx*8+:8] = RDATA_PENDING_VALUE_CONST[byte_idx*8+:8];
            end else begin
              capture_data_tclk[byte_idx*8+:8] = series_data_val_tclk[byte_idx*8+:8];
            end
          end
        end
        if ((series_read_preload_count_tclk == 0) && !series_rsp_fifo_empty_tclk && i_capture_en) begin
          series_rsp_fifo_pop_tclk = 1'b1;
        end
      end else begin
        for (int byte_idx = 0; byte_idx < DATA_WIDTH / 8; byte_idx++) begin
          if (byte_idx < num_bytes_to_copy) begin
            capture_data_tclk[byte_idx*8+:8] = series_data_val_tclk[byte_idx*8+:8];
          end
        end
      end

    end else if (i_select_AXISeriesDataWithErrorStatus) begin
      automatic logic [$clog2(SHARED_SR_LEN+1)-1:0] mapped_data_bits_cap_local;
      automatic int num_bytes_to_copy;
      automatic logic[DATA_WIDTH-1:0] capture_value_data_local;
      logic [1:0] captured_op_status_local;

      mapped_data_bits_cap_local = size_to_bits(3'(latched_series_size_for_len_tclk));
      if (mapped_data_bits_cap_local > DATA_WIDTH) mapped_data_bits_cap_local = DATA_WIDTH;
      num_bytes_to_copy = int'(mapped_data_bits_cap_local) >> 3;  // bits-to-bytes: divide by 8

      if (series_ctrl_op_mode_tclk_r == JTAG_OP_READ) begin
        if (series_errstat_pending_tclk) begin
          capture_value_data_local = RDATA_PENDING_VALUE_CONST;
          captured_op_status_local = CAPTURE_STATUS_BUSY_OR_FULL;
        end else begin
          capture_value_data_local = last_read_data_tclk;
          captured_op_status_local = last_single_op_status_tclk;
        end
      end else begin
        capture_value_data_local = series_data_errstat_val_tclk;
        captured_op_status_local = last_single_op_status_tclk;
      end

      for (int byte_idx = 0; byte_idx < DATA_WIDTH / 8; byte_idx++) begin
        if (byte_idx < num_bytes_to_copy) begin
          capture_data_tclk[byte_idx*8+:8] = capture_value_data_local[byte_idx*8+:8];
        end
      end

      if (mapped_data_bits_cap_local < SHARED_SR_LEN) begin
        if (series_errstat_pending_tclk) begin
          capture_data_tclk[mapped_data_bits_cap_local] = 1'b1;  // Busy
        end else begin
          if (captured_op_status_local == CAPTURE_STATUS_SUCCESS) begin
            capture_data_tclk[mapped_data_bits_cap_local] = 1'b0;
          end else begin
            capture_data_tclk[mapped_data_bits_cap_local] = 1'b1;
          end
        end
      end
    end
  end

endmodule : jtag2axi
