// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Generate single-beat AXI4 transactions from JTAG scan-chain inputs.
//
// All scan chains share one shift register, captured and shifted on rising TCK, and one
// update latch loaded on falling TCK; series reads and writes pipeline.
// AXISeriesCtrl.pipeline_depth programs 0..FIFO_DEPTH, larger values saturate, and the
// effective depth is pipeline_depth + 1.
// Every transaction carries ID 0, user 0, one INCR beat, AxCACHE 0b0010 and AxPROT 0b000.
// A scanned size wider than the bus is taken as one full beat: AxSIZE, the series write
// strobes, the series address step and the series data length all use the bus width.
//
// The following logic lives in the TCK domain:
//
// - TAP scan
// - command dispatch
// - AXI master FSM
// - series request/response FIFOs
// - sticky status
//
// The AXI master crosses into ACLK through one axi_cdc_clearable instance. A reset on either
// trst_ni or arst_ni runs its isolate-and-clear sequence on both sides.
// An ACLK-domain output stage buffers AW, W and AR, issues AW and W only as a pair, bounds
// outstanding transactions, and drains responses to requests issued before a CDC clear.
// When the clear reaches the TCK side, the bridge aborts every operation in flight or queued:
// the FSM returns to idle and holds there until the clear completes, the series FIFOs and
// pipeline accounting are flushed, and the status that reports an aborted operation reads
// DECERR. The sticky series status takes DECERR only while it holds no earlier error. Every
// other status, and the SERIES_CTRL configuration, is kept.
//
// Parameter constraints:
//
// - Address and data widths are parametrizable; DATA_WIDTH must be a power of 2 and a
//   multiple of 8.
// - ATOP_WIDTH must be 6 to match the PULP AXI channel typedef layout.
// - ADDR_WIDTH must cover the byte offset within one data beat.

module jtag2axi #(
  parameter int ADDR_WIDTH   = 52,      // Address width.
  parameter int DATA_WIDTH   = 64,      // Width of AXI read and write data and of the scan-chain
                                        // data fields; a power of 2 from 8 to 1024.
  parameter int ID_WIDTH     = 1,       // AXI ID width; IDs are always driven zero.
  parameter int USER_WIDTH   = 1,       // AXI user width; user fields are always driven zero.
  parameter int FIFO_DEPTH   = 2,       // Largest programmable AXISeriesCtrl.pipeline_depth; the
                                        // series request FIFO holds FIFO_DEPTH + 1 entries.
  parameter int ATOP_WIDTH   = 6        // AWATOP width; must be 6 for PULP AXI typedefs.
) (
  input  logic        tck_i,            // JTAG Test Clock.
  input  logic        trst_ni,          // JTAG Test Reset (active low); resets all TCK-domain state
                                        // and the CDC source side.

  input  logic        scan_in_i,        // JTAG Scan Data In (TDI).
  output logic        scan_out_o,       // JTAG Scan Data Out (TDO), bit 0 of the shared shift
                                        // register.

  input  logic        capture_en_i,     // JTAG Capture Enable (Capture-DR state).
  input  logic        shift_en_i,       // JTAG Shift Enable (Shift-DR state).
  input  logic        update_en_i,      // JTAG Update Enable (Update-DR state).

  input  logic        select_AXISingleOp_i,  // Select AXISingleOp scan chain.
  input  logic        select_AXISeriesCtrl_i,  // Select AXISeriesCtrl scan chain.
  input  logic        select_AXISeriesDataIncr_i,  // Select AXISeriesDataIncr scan chain.
  input  logic        select_AXISeriesDataNoIncr_i,  // Select AXISeriesDataNoIncr scan chain.
  input  logic        select_AXISeriesDataWithErrorStatus_i,  // Select AXISeriesDataWithErrorStatus
                                                              // scan chain.
  input  logic        security_disable_i,  // Active-high bridge disable: blocks Update-DR, keeps
                                           // the AXI FSM idle, and flushes queued requests once the
                                           // FSM is idle.

  input  logic        aclk_i,           // AXI Clock.
  input  logic        arst_ni,          // AXI Reset (active low), for the CDC destination side and
                                        // the ACLK output stage.
  input  logic        test_en_i,        // DFT test-mode enable, active-high, for the ACLK output
                                        // stage fall-through registers.

  output logic [ID_WIDTH-1:0]     awid_o,  // Write-address ID, always zero.
  output logic [ADDR_WIDTH-1:0]   awaddr_o,  // Write address.
  output logic [7:0]              awlen_o,  // Write burst length, always zero for a single beat.
  output logic [2:0]              awsize_o,  // Write beat size: the scanned size, at most the bus width.
  output logic [1:0]              awburst_o,  // Write burst type, always INCR.
  output logic                    awlock_o,  // Write lock, always zero.
  output logic [3:0]              awcache_o,  // Write cache attributes, always 0b0010.
  output logic [2:0]              awprot_o,  // Write protection attributes, always 0b000.
  output logic [3:0]              awqos_o,  // Write QoS, always zero.
  output logic [3:0]              awregion_o,  // Write region, always zero.
  output logic [USER_WIDTH-1:0]   awuser_o,  // Write-address user, always zero.
  output logic [ATOP_WIDTH-1:0]   awatop_o,  // Write atomic op (AWATOP), always zero.
  output logic                    awvalid_o,  // Write-address valid.
  input  logic                    awready_i,  // Write-address ready.

  output logic [DATA_WIDTH-1:0]   wdata_o,  // Write data.
  output logic [DATA_WIDTH/8-1:0] wstrb_o,  // Write strobes.
  output logic                    wlast_o,  // Write last, always high for the single beat.
  output logic [USER_WIDTH-1:0]   wuser_o,  // Write-data user, always zero.
  output logic                    wvalid_o,  // Write-data valid.
  input  logic                    wready_i,  // Write-data ready.

  input  logic [ID_WIDTH-1:0]     bid_i,  // Write-response ID.
  input  logic [1:0]              bresp_i,  // Write-response status.
  input  logic [USER_WIDTH-1:0]   buser_i,  // Write-response user.
  input  logic                    bvalid_i,  // Write-response valid.
  output logic                    bready_o,  // Write-response ready.

  output logic [ID_WIDTH-1:0]     arid_o,  // Read-address ID, always zero.
  output logic [ADDR_WIDTH-1:0]   araddr_o,  // Read address.
  output logic [7:0]              arlen_o,  // Read burst length, always zero for a single beat.
  output logic [2:0]              arsize_o,  // Read beat size: the scanned size, at most the bus width.
  output logic [1:0]              arburst_o,  // Read burst type, always INCR.
  output logic                    arlock_o,  // Read lock, always zero.
  output logic [3:0]              arcache_o,  // Read cache attributes, always 0b0010.
  output logic [2:0]              arprot_o,  // Read protection attributes, always 0b000.
  output logic [3:0]              arqos_o,  // Read QoS, always zero.
  output logic [3:0]              arregion_o,  // Read region, always zero.
  output logic [USER_WIDTH-1:0]   aruser_o,  // Read-address user, always zero.
  output logic                    arvalid_o,  // Read-address valid.
  input  logic                    arready_i,  // Read-address ready.

  input  logic [ID_WIDTH-1:0]     rid_i,  // Read-data ID.
  input  logic [DATA_WIDTH-1:0]   rdata_i,  // Read data.
  input  logic [1:0]              rresp_i,  // Read-response status.
  input  logic                    rlast_i,  // Read last.
  input  logic [USER_WIDTH-1:0]   ruser_i,  // Read-data user.
  input  logic                    rvalid_i,  // Read-data valid.
  output logic                    rready_o  // Read-data ready.
);

  `include "axi/typedef.svh"
  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  //--------------------------------------------------------------------------
  // Local Parameters and Constants
  //--------------------------------------------------------------------------

  // JTAG Operation Codes
  localparam logic [1:0] JtagOpNop = 2'b00;
  localparam logic [1:0] JtagOpRead = 2'b01;
  localparam logic [1:0] JtagOpWrite = 2'b10;

  // AXI Status Codes for JTAG Capture
  localparam logic [1:0] CaptureStatusSuccess = 2'b00;
  localparam logic [1:0] CaptureStatusSlverr = 2'b01;
  localparam logic [1:0] CaptureStatusDecerr = 2'b10;
  localparam logic [1:0] CaptureStatusBusyOrFull = 2'b11;

  // AXI Constants
  localparam logic [1:0] AxiBurstIncr = 2'b01;
  localparam logic [7:0] AxiLenSingle = 8'b00000000;
  localparam logic [2:0] AxiProtDefault = 3'b000;  // Unprivileged, Secure, Data
  localparam logic [3:0] AxiCacheDefault = 4'b0010;  // Normal Non-cacheable Non-bufferable

  localparam logic [1023:0] DeadBeefConst = {32{32'hDEADBEEF}};
  logic [DATA_WIDTH-1:0] RDATA_PENDING_VALUE_CONST;
  assign RDATA_PENDING_VALUE_CONST = DeadBeefConst[DATA_WIDTH-1:0];

  // Size field width: 1 bit for 8-16, 2 bits for 32-64, 3 bits for 128-1024
  localparam int ScanChainSizeFieldWidth = (DATA_WIDTH <= 16) ? 1 : (DATA_WIDTH <= 64) ? 2 : 3;
  localparam int WstrbFieldWidth = DATA_WIDTH / 8;
  localparam int PipelineDepthFieldBits = (FIFO_DEPTH == 0) ? 1 : $clog2(FIFO_DEPTH + 1);

  localparam int AxiSingleOpOpBits = 2;
  localparam int AxiSingleOpSizeBits = ScanChainSizeFieldWidth;
  localparam int AxiSingleOpWstrbBits = WstrbFieldWidth;
  localparam int AxiSingleOpDataBits = DATA_WIDTH;
  localparam int AxiSingleOpAddrBits = ADDR_WIDTH;
  localparam int AxiSingleOpOpLow = 0;
  localparam int AxiSingleOpOpHigh = AxiSingleOpOpLow + AxiSingleOpOpBits - 1;
  localparam int AxiSingleOpSizeLow = AxiSingleOpOpHigh + 1;
  localparam int AxiSingleOpSizeHigh = AxiSingleOpSizeLow + AxiSingleOpSizeBits - 1;
  localparam int AxiSingleOpWstrbLow = AxiSingleOpSizeHigh + 1;
  localparam int AxiSingleOpWstrbHigh = AxiSingleOpWstrbLow + AxiSingleOpWstrbBits - 1;
  localparam int AxiSingleOpDataLow = AxiSingleOpWstrbHigh + 1;
  localparam int AxiSingleOpDataHigh = AxiSingleOpDataLow + AxiSingleOpDataBits - 1;
  localparam int AxiSingleOpAddrLow = AxiSingleOpDataHigh + 1;
  localparam int AxiSingleOpAddrHigh = AxiSingleOpAddrLow + AxiSingleOpAddrBits - 1;
  localparam int AxiSingleOpLen = AxiSingleOpAddrHigh + 1;

  localparam int AxiSeriesCtrlOpBits = 2;
  localparam int AxiSeriesCtrlSizeBits = ScanChainSizeFieldWidth;
  localparam int AxiSeriesCtrlPdBits = PipelineDepthFieldBits;
  localparam int AxiSeriesCtrlAddrBits = ADDR_WIDTH;
  localparam int AxiSeriesCtrlResetBits = 1;
  localparam int AxiSeriesCtrlOpLow = 0;
  localparam int AxiSeriesCtrlOpHigh = AxiSeriesCtrlOpLow + AxiSeriesCtrlOpBits - 1;
  localparam int AxiSeriesCtrlSizeLow = AxiSeriesCtrlOpHigh + 1;
  localparam int AxiSeriesCtrlSizeHigh = AxiSeriesCtrlSizeLow + AxiSeriesCtrlSizeBits - 1;
  localparam int AxiSeriesCtrlPdLow = AxiSeriesCtrlSizeHigh + 1;
  localparam int AxiSeriesCtrlPdHigh = AxiSeriesCtrlPdLow + AxiSeriesCtrlPdBits - 1;
  localparam int AxiSeriesCtrlAddrLow = AxiSeriesCtrlPdHigh + 1;
  localparam int AxiSeriesCtrlAddrHigh = AxiSeriesCtrlAddrLow + AxiSeriesCtrlAddrBits - 1;
  localparam int AxiSeriesCtrlResetLow = AxiSeriesCtrlAddrHigh + 1;
  localparam int AxiSeriesCtrlResetHigh = AxiSeriesCtrlResetLow + AxiSeriesCtrlResetBits - 1;
  localparam int AxiSeriesCtrlLen = AxiSeriesCtrlResetHigh + 1;

  localparam int SeriesDataMaxMappedBits = DATA_WIDTH;
  localparam int AxiSeriesDataIncrMaxLen = SeriesDataMaxMappedBits;
  localparam int AxiSeriesDataNoIncrMaxLen = SeriesDataMaxMappedBits;
  localparam int AxiSeriesDataWithErrorStatusMaxLen = SeriesDataMaxMappedBits + 1;

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

  // READ and WRITE are the only op codes that issue an AXI transfer.
  function automatic logic is_axi_op(input logic [1:0] op);
    return (op == JtagOpRead) || (op == JtagOpWrite);
  endfunction

  localparam int SharedSrLen = max4(
      AxiSingleOpLen, AxiSeriesCtrlLen, AxiSeriesDataIncrMaxLen, AxiSeriesDataWithErrorStatusMaxLen
  );
  localparam int SeriesRspFifoSize = FIFO_DEPTH + 1;
  localparam int CdcLogDepth = (FIFO_DEPTH + 2 <= 2) ? 1 : $clog2(FIFO_DEPTH + 2);
  localparam int unsigned BeatBytes = DATA_WIDTH / 8;
  localparam int unsigned ByteOffsetBits = (BeatBytes <= 1) ? 0 : $clog2(BeatBytes);
  localparam logic [2:0] MaxAxSize = 3'(ByteOffsetBits);

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
    localparam int unsigned OffW = (ByteOffsetBits == 0) ? 1 : ByteOffsetBits;
    logic [OffW-1:0] offset_bits;
    offset_bits = '0;
    if (ByteOffsetBits != 0) begin
      offset_bits = addr[OffW-1:0];
    end
    return (ByteOffsetBits == 0) ? 0 : int'(offset_bits);
  endfunction

  function automatic j2a_strb_t series_lane_wstrb(input logic [ADDR_WIDTH-1:0] addr,
                                                  input logic [2:0] axsize);
    automatic int unsigned offset = beat_byte_offset(addr);
    automatic int unsigned num_bytes = size_to_bytes(axsize);
    automatic j2a_strb_t mask;
    if (num_bytes >= BeatBytes) begin
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
  logic [SharedSrLen-1:0] shift_register_q_tclk;
  logic [SharedSrLen-1:0] update_register_q_tclk;
  logic [SharedSrLen-1:0] capture_data_tclk;

  logic [ScanChainSizeFieldWidth-1:0] latched_series_size_for_len_tclk;
  logic [$clog2(SharedSrLen+1)-1:0] active_instr_len_tclk;

  always_ff @(negedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      latched_series_size_for_len_tclk <= '0;
    end else begin
      if (update_en_i && select_AXISeriesCtrl_i && !security_disable_i) begin
        latched_series_size_for_len_tclk <= shift_register_q_tclk[AxiSeriesCtrlSizeHigh : AxiSeriesCtrlSizeLow];
      end
    end
  end

  always_comb begin
    active_instr_len_tclk = SharedSrLen;
    if (select_AXISingleOp_i) begin
      active_instr_len_tclk = AxiSingleOpLen;
    end else if (select_AXISeriesCtrl_i) begin
      active_instr_len_tclk = AxiSeriesCtrlLen;
    end else if (select_AXISeriesDataIncr_i || select_AXISeriesDataNoIncr_i || select_AXISeriesDataWithErrorStatus_i) begin
      automatic int mapped_data_bits_local;
      mapped_data_bits_local = size_to_bits(3'(latched_series_size_for_len_tclk));
      if (mapped_data_bits_local > DATA_WIDTH) mapped_data_bits_local = DATA_WIDTH;
      if (select_AXISeriesDataIncr_i || select_AXISeriesDataNoIncr_i) begin
        active_instr_len_tclk = mapped_data_bits_local;
      end else if (select_AXISeriesDataWithErrorStatus_i) begin
        active_instr_len_tclk = mapped_data_bits_local + 1;
      end
    end
    if (active_instr_len_tclk == 0 &&
            (select_AXISingleOp_i || select_AXISeriesCtrl_i || select_AXISeriesDataIncr_i ||
             select_AXISeriesDataNoIncr_i || select_AXISeriesDataWithErrorStatus_i) ) begin
      active_instr_len_tclk = 1;
    end
    if (active_instr_len_tclk > SharedSrLen) begin
      active_instr_len_tclk = SharedSrLen;
    end
  end

  logic [SharedSrLen-1:0] shift_register_d_tclk;

  always_comb begin
    automatic logic [SharedSrLen-1:0]            next_sr_val;
    automatic logic [$clog2(SharedSrLen+1)-1:0] current_len;

    shift_register_d_tclk = shift_register_q_tclk;
    current_len = active_instr_len_tclk;
    next_sr_val = shift_register_q_tclk;

    if (capture_en_i) begin
      shift_register_d_tclk = capture_data_tclk;
    end else if (shift_en_i) begin
      if (current_len > 0 && current_len <= SharedSrLen) begin
        next_sr_val[current_len-1] = scan_in_i;
        for (int bit_idx = 0; bit_idx < SharedSrLen - 1; bit_idx = bit_idx + 1) begin
          if (bit_idx < int'(current_len) - 1) begin
            next_sr_val[bit_idx] = shift_register_q_tclk[bit_idx+1];
          end
        end
      end
      shift_register_d_tclk = next_sr_val;
    end
  end

  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      shift_register_q_tclk <= '0;
    end else begin
      shift_register_q_tclk <= shift_register_d_tclk;
    end
  end

  always_ff @(negedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      update_register_q_tclk <= '0;
    end else begin
      if (update_en_i && !security_disable_i) begin
        update_register_q_tclk <= shift_register_q_tclk;
      end
    end
  end
  assign scan_out_o = shift_register_q_tclk[0];

  //--------------------------------------------------------------------------
  // JTAG Scan Chain Data Extraction (TCK Domain)
  //--------------------------------------------------------------------------
  logic [AxiSingleOpOpBits-1:0]    single_op_op_tclk;
  logic [AxiSingleOpSizeBits-1:0]  single_op_size_tclk;
  logic [AxiSingleOpWstrbBits-1:0] single_op_wstrb_tclk;
  logic [AxiSingleOpDataBits-1:0]  single_op_data_tclk;
  logic [AxiSingleOpAddrBits-1:0]  single_op_addr_tclk;

  assign single_op_op_tclk    = update_register_q_tclk[AxiSingleOpOpHigh    : AxiSingleOpOpLow];
  assign single_op_size_tclk  = update_register_q_tclk[AxiSingleOpSizeHigh  : AxiSingleOpSizeLow];
  assign single_op_wstrb_tclk = update_register_q_tclk[AxiSingleOpWstrbHigh : AxiSingleOpWstrbLow];
  assign single_op_data_tclk  = update_register_q_tclk[AxiSingleOpDataHigh  : AxiSingleOpDataLow];
  assign single_op_addr_tclk  = update_register_q_tclk[AxiSingleOpAddrHigh  : AxiSingleOpAddrLow];

  logic [DATA_WIDTH-1:0] series_data_val_tclk;
  assign series_data_val_tclk = update_register_q_tclk[DATA_WIDTH-1:0];

  logic [DATA_WIDTH-1:0] series_data_errstat_val_tclk;
  logic                  series_data_errstat_incr_stat_bit_tclk;

  always_comb begin
    automatic logic [$clog2(SharedSrLen+1)-1:0] current_mapped_data_len_local;
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

    if (current_mapped_data_len_local < SharedSrLen) begin
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
  logic [ScanChainSizeFieldWidth-1:0]     single_tx_axi_size_tclk;
  logic [WstrbFieldWidth-1:0]             single_tx_wstrb_tclk;

  // Series control state
  logic [AxiSeriesCtrlSizeBits-1:0]   series_ctrl_size_tclk_r;
  logic [AxiSeriesCtrlPdBits-1:0]     series_ctrl_pipeline_depth_tclk_r;
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
  logic [PipelineDepthFieldBits-1:0] series_read_preload_count_tclk;

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
  // Combinational pulse asserted on a CTRL Update-DR with a READ or WRITE
  // op. A new CTRL programming flushes all queued series request/response
  // state from any prior programming.
  logic                            ctrl_flush_pulse_tclk;
  logic [1:0]                      series_ctrl_update_op_tclk;
  logic                            series_mode_is_axi_tclk;
  // `series_reads_pushed_tclk`: total series read requests enqueued via
  //   JTAG Update-DR since the last READ or WRITE CTRL programming. Bounded at
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
    logic [ScanChainSizeFieldWidth-1:0]     jtag_size;
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

  logic [$clog2(SeriesRspFifoSize+1)-1:0]    series_rsp_fifo_count_tclk;
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
  logic [ScanChainSizeFieldWidth-1:0]     current_jtag_size_tclk;
  logic [WstrbFieldWidth-1:0]             current_custom_wstrb_tclk;
  logic                                   current_use_custom_wstrb_tclk;
  logic                                   current_incr_series_addr_tclk;
  logic                                   current_tx_is_series_read_tclk;
  logic                                   current_tx_is_from_single_buffer_tclk;
  logic                                   current_is_series_data_with_error_status_op_tclk;

  // Derived
  logic [2:0]                   current_axi_axsize_tclk;
  logic [WstrbFieldWidth-1:0]   current_wstrb_tclk;
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

  logic src_clear_pending_tclk;
  logic src_clear_pending_q_tclk;
  logic cdc_clear_abort_tclk;
  logic single_op_aborted_tclk;
  logic series_aborted_tclk;

  logic write_discard_rsp_q;
  logic read_discard_rsp_q;

  localparam logic [1:0] OutstandingMax = 2'b11;
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
    .LogDepth          (CdcLogDepth),
    .SyncStages        (3),
    .ClearOnAsyncReset (1'b1)
  ) u_axi_cdc (
    .src_clk_i           (tck_i),
    .src_rst_ni          (trst_ni),
    .src_clear_i         (1'b0),
    .src_clear_pending_o (src_clear_pending_tclk),
    .src_req_i           (src_req),
    .src_resp_o          (src_resp),
    .dst_clk_i           (aclk_i),
    .dst_rst_ni          (arst_ni),
    .dst_clear_i         (1'b0),
    .dst_clear_pending_o (dst_clear_pending),
    .dst_req_o           (dst_req),
    .dst_resp_i          (dst_resp)
  );

  //--------------------------------------------------------------------------
  // CDC clear abort (TCK)
  //--------------------------------------------------------------------------
  // The CDC isolates the TCK side before clearing it, so no B or R beat
  // reaches the FSM while src_clear_pending_tclk is high. A request that was
  // already pushed into the CDC is dropped by the clear and never completes.
  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      src_clear_pending_q_tclk <= 1'b0;
    end else begin
      src_clear_pending_q_tclk <= src_clear_pending_tclk;
    end
  end

  assign cdc_clear_abort_tclk = src_clear_pending_tclk && !src_clear_pending_q_tclk;

  assign single_op_aborted_tclk = single_op_pending_tclk || series_errstat_pending_tclk;
  assign series_aborted_tclk =
        series_errstat_pending_tclk ||
        ((axi_state_q_tclk != AXI_IDLE) && (axi_state_q_tclk != AXI_UPDATE_STATUS) &&
         !current_tx_is_from_single_buffer_tclk) ||
        !series_request_fifo_empty_tclk || series_request_fifo_push_tclk ||
        !series_rsp_fifo_empty_tclk;

  //--------------------------------------------------------------------------
  // ACLK-domain TLR-safe AXI output stage
  //--------------------------------------------------------------------------

  assign dst_clear_start = dst_clear_pending && !dst_clear_pending_q;

  // Do not consume a CDC beat after its clear sequence has started. A
  // partially assembled write is flushed; a complete pair is drained.
  assign dst_resp.aw_ready = !dst_clear_pending && aw_buf_ready &&
                               (write_outstanding_q != OutstandingMax);
  assign dst_resp.w_ready  = !dst_clear_pending && w_buf_ready &&
                               (write_outstanding_q != OutstandingMax);
  assign dst_resp.ar_ready = !dst_clear_pending && ar_buf_ready &&
                               (read_outstanding_q != OutstandingMax);

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
    .clk_i      (aclk_i),
    .rst_ni     (arst_ni),
    .clr_i       (write_pair_flush),
    .testmode_i (test_en_i),
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
    .clk_i      (aclk_i),
    .rst_ni     (arst_ni),
    .clr_i       (write_pair_flush),
    .testmode_i (test_en_i),
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
    .clk_i   (aclk_i),
    .rst_ni  (arst_ni),
    .valid_i (write_pair_valid),
    .ready_o (write_pair_ready),
    .valid_o (write_fork_valid),
    .ready_i ({awready_i, wready_i})
  );

  fall_through_register #(
    .T(j2a_ar_t)
  ) u_ar_ft_reg (
    .clk_i      (aclk_i),
    .rst_ni     (arst_ni),
    .clr_i       (1'b0),
    .testmode_i (test_en_i),
    .valid_i    (ar_input_valid),
    .ready_o    (ar_buf_ready),
    .data_i     (dst_req.ar),
    .valid_o    (ar_buf_valid),
    .ready_i    (arready_i),
    .data_o     (ar_buf)
  );

  assign awvalid_o = write_fork_valid[1];
  assign wvalid_o  = write_fork_valid[0];
  assign arvalid_o = ar_buf_valid;

  assign ar_handshake = arvalid_o && arready_i;
  assign write_complete = write_pair_valid && write_pair_ready;

  assign write_completion_is_orphan = write_discard_rsp_q || dst_clear_start;
  assign read_completion_is_orphan  = read_discard_rsp_q || dst_clear_start;

  assign awid_o     = aw_buf.id;
  assign awaddr_o   = aw_buf.addr;
  assign awlen_o    = aw_buf.len;
  assign awsize_o   = aw_buf.size;
  assign awburst_o  = aw_buf.burst;
  assign awlock_o   = aw_buf.lock;
  assign awcache_o  = aw_buf.cache;
  assign awprot_o   = aw_buf.prot;
  assign awqos_o    = aw_buf.qos;
  assign awregion_o = aw_buf.region;
  assign awuser_o   = aw_buf.user;
  assign awatop_o   = aw_buf.atop;

  assign wdata_o = w_buf.data;
  assign wstrb_o = w_buf.strb;
  assign wlast_o = w_buf.last;
  assign wuser_o = w_buf.user;

  assign arid_o     = ar_buf.id;
  assign araddr_o   = ar_buf.addr;
  assign arlen_o    = ar_buf.len;
  assign arsize_o   = ar_buf.size;
  assign arburst_o  = ar_buf.burst;
  assign arlock_o   = ar_buf.lock;
  assign arcache_o  = ar_buf.cache;
  assign arprot_o   = ar_buf.prot;
  assign arqos_o    = ar_buf.qos;
  assign arregion_o = ar_buf.region;
  assign aruser_o   = ar_buf.user;

  // All requests outstanding when a clear starts belong to the old JTAG
  // session.  Consume their ordered responses locally instead of allowing a
  // stale B or R beat to satisfy the first request of the new session.
  // A slave may return a response in the same cycle as the final request
  // handshake.  Include that just-completed request here rather than
  // inserting a response-channel bubble.
  assign bready_o = ((write_outstanding_q != '0) || write_complete) &&
                      ((orphan_b_count_q != '0) ||
                       (write_complete && write_completion_is_orphan) ||
                       (!dst_clear_pending && dst_req.b_ready));
  assign rready_o = ((read_outstanding_q != '0) || ar_handshake) &&
                      ((orphan_r_count_q != '0) ||
                       (ar_handshake && read_completion_is_orphan) ||
                       (!dst_clear_pending && dst_req.r_ready));

  assign dst_resp.b_valid = bvalid_i &&
                              ((write_outstanding_q != '0) || write_complete) &&
                              (orphan_b_count_q == '0) && !dst_clear_pending;
  assign dst_resp.b.id     = bid_i;
  assign dst_resp.b.resp   = bresp_i;
  assign dst_resp.b.user   = buser_i;
  assign dst_resp.r_valid  = rvalid_i &&
                               ((read_outstanding_q != '0) || ar_handshake) &&
                               (orphan_r_count_q == '0) && !dst_clear_pending;
  assign dst_resp.r.id     = rid_i;
  assign dst_resp.r.data   = rdata_i;
  assign dst_resp.r.resp   = rresp_i;
  assign dst_resp.r.last   = rlast_i;
  assign dst_resp.r.user   = ruser_i;

  assign b_handshake      = bvalid_i && bready_o;
  assign r_handshake      = rvalid_i && rready_o;
  assign r_last_handshake = r_handshake && rlast_i;

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

  always_ff @(posedge aclk_i or negedge arst_ni) begin
    if (!arst_ni) begin
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

`ifdef OCAH_DEBUG_LIVE
  `OCAH_OT_ASSERT(AwValidStable_A, awvalid_o && !awready_i |=> awvalid_o && $stable(aw_buf),
                  aclk_i, !arst_ni)
  `OCAH_OT_ASSERT(WValidStable_A, wvalid_o && !wready_i |=> wvalid_o && $stable(w_buf), aclk_i,
                  !arst_ni)
  `OCAH_OT_ASSERT(ArValidStable_A, arvalid_o && !arready_i |=> arvalid_o && $stable(ar_buf),
                  aclk_i, !arst_ni)
  `OCAH_OT_ASSERT(AwHasWriteData_A, awvalid_o |-> w_buf_valid, aclk_i, !arst_ni)
  `OCAH_OT_ASSERT(WaHasWriteAddress_A, wvalid_o |-> aw_buf_valid, aclk_i, !arst_ni)
  `OCAH_OT_ASSERT(ClearPendingHoldsIdle_A, src_clear_pending_tclk |=> axi_state_q_tclk == AXI_IDLE,
                  tck_i, !trst_ni)
`endif

  //--------------------------------------------------------------------------
  // Series Request FIFO Storage (TCK)
  //--------------------------------------------------------------------------
  assign series_ctrl_update_op_tclk =
        update_register_q_tclk[AxiSeriesCtrlOpHigh:AxiSeriesCtrlOpLow];
  assign series_mode_is_axi_tclk = is_axi_op(series_ctrl_op_mode_tclk_r);
  assign ctrl_flush_pulse_tclk = update_en_i && !security_disable_i &&
        select_AXISeriesCtrl_i && is_axi_op(series_ctrl_update_op_tclk);

  localparam int unsigned ReqFifoDepth = FIFO_DEPTH + 1;
  localparam int unsigned ReqFifoWidth = $bits(series_request_fifo_entry_t);

  logic req_fifo_full_internal_tclk;
  logic req_fifo_clr_tclk;

  assign req_fifo_clr_tclk =
        (security_disable_i && (axi_state_q_tclk == AXI_IDLE)) ||
        ctrl_flush_pulse_tclk || cdc_clear_abort_tclk;

  prim_fifo_sync #(
    .Width            (ReqFifoWidth),
    .Depth            (ReqFifoDepth),
    .Pass             (1'b0),
    .OutputZeroIfEmpty(1'b0),
    .NeverClears      (1'b0),
    .Secure           (1'b0)
  ) u_series_request_fifo (
    .clk_i   (tck_i),
    .rst_ni  (trst_ni),
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
        ctrl_flush_pulse_tclk || cdc_clear_abort_tclk;

  prim_fifo_sync #(
    .Width            (RspFifoWidth),
    .Depth            (SeriesRspFifoSize),
    .Pass             (1'b0),
    .OutputZeroIfEmpty(1'b0),
    .NeverClears      (1'b0),
    .Secure           (1'b0)
  ) u_series_rsp_fifo (
    .clk_i   (tck_i),
    .rst_ni  (trst_ni),
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
  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      axi_state_q_tclk                                 <= AXI_IDLE;
      current_tx_is_series_read_tclk                   <= 1'b0;
      current_tx_is_from_single_buffer_tclk            <= 1'b0;
      current_is_series_data_with_error_status_op_tclk <= 1'b0;
      current_op_tclk                                  <= JtagOpNop;
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
                        (series_request_fifo_dout_tclk.op == JtagOpRead);
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
        current_op_tclk                                  <= JtagOpNop;
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
          if (single_tx_op_tclk == JtagOpWrite) begin
            axi_state_d_tclk = AXI_SEND_ADDR_W;
          end else if (single_tx_op_tclk == JtagOpRead) begin
            axi_state_d_tclk = AXI_SEND_ADDR_R;
          end else begin
            axi_state_d_tclk = AXI_IDLE;
          end
        end else if (!series_request_fifo_empty_tclk) begin
          if (series_request_fifo_dout_tclk.op == JtagOpRead) begin
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
                        (src_resp.b.resp == 2'b00) ? CaptureStatusSuccess :
                        (src_resp.b.resp == 2'b10) ? CaptureStatusSlverr  :
                        (src_resp.b.resp == 2'b11) ? CaptureStatusDecerr  :
                                                     CaptureStatusSlverr;
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
                        (src_resp.r.resp == 2'b00) ? CaptureStatusSuccess :
                        (src_resp.r.resp == 2'b10) ? CaptureStatusSlverr  :
                        (src_resp.r.resp == 2'b11) ? CaptureStatusDecerr  :
                                                     CaptureStatusSlverr;
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

    if (src_clear_pending_tclk) begin
      axi_state_d_tclk                   = AXI_IDLE;
      series_request_fifo_pop_tclk       = 1'b0;
      src_req.aw_valid                   = 1'b0;
      src_req.w_valid                    = 1'b0;
      src_req.b_ready                    = 1'b0;
      src_req.ar_valid                   = 1'b0;
      src_req.r_ready                    = 1'b0;
      fsm_updates_bresp_status_tclk_comb = 1'b0;
      fsm_updates_rdata_status_tclk_comb = 1'b0;
    end
  end

  //--------------------------------------------------------------------------
  // src_req AW/W/AR channel struct population (constant fields + dynamic)
  //--------------------------------------------------------------------------
  always_comb begin
    src_req.aw        = '0;
    src_req.aw.id     = ID_WIDTH'(0);
    src_req.aw.addr   = current_addr_tclk;
    src_req.aw.len    = AxiLenSingle;
    src_req.aw.size   = current_axi_axsize_tclk;
    src_req.aw.burst  = AxiBurstIncr;
    src_req.aw.lock   = 1'b0;
    src_req.aw.cache  = AxiCacheDefault;
    src_req.aw.prot   = AxiProtDefault;
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
    src_req.ar.len    = AxiLenSingle;
    src_req.ar.size   = current_axi_axsize_tclk;
    src_req.ar.burst  = AxiBurstIncr;
    src_req.ar.lock   = 1'b0;
    src_req.ar.cache  = AxiCacheDefault;
    src_req.ar.prot   = AxiProtDefault;
    src_req.ar.qos    = 4'b0;
    src_req.ar.region = 4'b0;
    src_req.ar.user   = USER_WIDTH'(0);
  end

  // AxSIZE must not exceed the bus width (IHI 0022 A3.4.1).
  always_comb begin
    current_axi_axsize_tclk = 3'(current_jtag_size_tclk);
    if (current_axi_axsize_tclk > MaxAxSize) begin
      current_axi_axsize_tclk = MaxAxSize;
    end
  end

  // current_wstrb: custom mask for single-buffer writes, lane-aligned
  // generated mask for series writes.
  always_comb begin
    current_wstrb_tclk = '0;
    if (current_op_tclk == JtagOpWrite) begin
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
  logic [ScanChainSizeFieldWidth-1:0]     single_tx_axi_size_tclk_d;
  logic [WstrbFieldWidth-1:0]             single_tx_wstrb_tclk_d;

  logic [AxiSeriesCtrlSizeBits-1:0]   series_ctrl_size_tclk_r_d;
  logic [AxiSeriesCtrlPdBits-1:0]     series_ctrl_pipeline_depth_tclk_r_d;
  logic [ADDR_WIDTH-1:0]              series_ctrl_address_tclk_r_d;
  logic [1:0]                         series_ctrl_op_mode_tclk_r_d;

  logic                  single_op_pending_tclk_d;
  logic                  series_errstat_pending_tclk_d;
  logic [1:0]            last_single_op_status_tclk_d;
  logic [DATA_WIDTH-1:0] last_read_data_tclk_d;
  logic                  last_single_op_was_read_tclk_d;
  logic [1:0]            sticky_axi_status_tclk_d;
  logic                  sticky_axi_status_full_tclk_d;
  logic                  series_status_takes_completion;

  logic [PipelineDepthFieldBits-1:0]    series_read_preload_count_tclk_d;
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

    // An Update-DR in the same cycle is dispatched below against the
    // pre-abort busy state.
    if (cdc_clear_abort_tclk) begin
      single_tx_req_valid_tclk_d       = 1'b0;
      single_op_pending_tclk_d         = 1'b0;
      series_errstat_pending_tclk_d    = 1'b0;
      series_read_preload_count_tclk_d = '0;
      plain_reads_pending_tclk_d       = '0;
      series_reads_in_flight_tclk_d    = '0;
      series_reads_pushed_tclk_d       = '0;
      if (single_op_aborted_tclk) begin
        last_single_op_status_tclk_d = CaptureStatusDecerr;
        last_read_data_tclk_d        = '0;
      end
      if (series_aborted_tclk && (sticky_axi_status_tclk_d == CaptureStatusSuccess)) begin
        sticky_axi_status_tclk_d = CaptureStatusDecerr;
      end
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
      last_single_op_was_read_tclk_d = (single_tx_op_tclk == JtagOpRead);
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
    if (update_en_i && !security_disable_i) begin
      if (select_AXISingleOp_i) begin
        automatic logic [1:0] single_op_val;
        single_op_val = update_register_q_tclk[AxiSingleOpOpHigh:AxiSingleOpOpLow];
        // READ/WRITE while a beat is in flight is a rejected operation.
        // NOP (and reserved) Update-DR is a status poll and must not set
        // sticky_full or clear pending.
        if (single_op_val == JtagOpRead || single_op_val == JtagOpWrite) begin
          if (!(axi_transaction_in_progress_tclk || single_tx_req_valid_tclk)) begin
            single_tx_req_valid_tclk_d     = 1'b1;
            single_tx_op_tclk_d            = single_op_val;
            single_tx_addr_tclk_d          = update_register_q_tclk[AxiSingleOpAddrHigh : AxiSingleOpAddrLow];
            single_tx_data_tclk_d          = update_register_q_tclk[AxiSingleOpDataHigh : AxiSingleOpDataLow];
            single_tx_axi_size_tclk_d      = update_register_q_tclk[AxiSingleOpSizeHigh : AxiSingleOpSizeLow];
            single_tx_wstrb_tclk_d         = update_register_q_tclk[AxiSingleOpWstrbHigh: AxiSingleOpWstrbLow];
            single_op_pending_tclk_d       = 1'b1;
            last_single_op_was_read_tclk_d = (single_op_val == JtagOpRead);
          end else begin
            sticky_axi_status_full_tclk_d = 1'b1;
            last_single_op_status_tclk_d  = CaptureStatusBusyOrFull;
            single_op_pending_tclk_d      = 1'b0;
          end
        end
      end else if (select_AXISeriesCtrl_i) begin
        automatic logic [1:0] op_val;
        automatic logic [AxiSeriesCtrlPdBits-1:0] pd_val;
        op_val = update_register_q_tclk[AxiSeriesCtrlOpHigh:AxiSeriesCtrlOpLow];
        pd_val = (update_register_q_tclk[AxiSeriesCtrlPdHigh:AxiSeriesCtrlPdLow] > FIFO_DEPTH) ?
                         FIFO_DEPTH[PipelineDepthFieldBits-1:0] :
                         update_register_q_tclk[AxiSeriesCtrlPdHigh:AxiSeriesCtrlPdLow];

        // Only a READ or WRITE op reprograms series CTRL state
        // (including the read preload counter). A NOP or reserved
        // update, which CTRL TDR read-backs issue, leaves the
        // preload/address/pipeline-depth state accumulated by the
        // in-flight series operation intact.
        if (is_axi_op(op_val)) begin
          series_ctrl_size_tclk_r_d           = update_register_q_tclk[AxiSeriesCtrlSizeHigh:AxiSeriesCtrlSizeLow];
          series_ctrl_pipeline_depth_tclk_r_d = pd_val;
          series_ctrl_address_tclk_r_d        = update_register_q_tclk[AxiSeriesCtrlAddrHigh:AxiSeriesCtrlAddrLow];
          series_ctrl_op_mode_tclk_r_d        = op_val;
          if (op_val == JtagOpRead) begin
            series_read_preload_count_tclk_d = pd_val;
          end else begin
            series_read_preload_count_tclk_d = '0;
          end
          // `series_reads_pushed_tclk` and the other pipeline
          // accounting counters are flushed centrally via
          // `ctrl_flush_pulse_tclk`; nothing extra needed here.
        end
        if (update_register_q_tclk[AxiSeriesCtrlResetHigh]) begin
          sticky_axi_status_tclk_d      = CaptureStatusSuccess;
          sticky_axi_status_full_tclk_d = 1'b0;
        end
      end else if ((select_AXISeriesDataIncr_i || select_AXISeriesDataNoIncr_i ||
                          select_AXISeriesDataWithErrorStatus_i) && series_mode_is_axi_tclk) begin
        automatic logic [$clog2(SharedSrLen+1)-1:0] current_mapped_data_len_local;
        automatic int num_bytes_to_copy;
        automatic logic [DATA_WIDTH-1:0] data_val;
        automatic logic incr_addr_bit;
        automatic logic can_accept;
        automatic logic budget_ok;
        automatic logic is_plain_read;

        data_val = update_register_q_tclk[DATA_WIDTH-1:0];
        incr_addr_bit = select_AXISeriesDataIncr_i;

        if (select_AXISeriesDataWithErrorStatus_i) begin
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
          if (current_mapped_data_len_local < SharedSrLen) begin
            incr_addr_bit = update_register_q_tclk[current_mapped_data_len_local];
          end else begin
            incr_addr_bit = 1'b0;
          end
        end

        is_plain_read = (series_ctrl_op_mode_tclk_r == JtagOpRead) &&
                                !select_AXISeriesDataWithErrorStatus_i;

        if (series_ctrl_op_mode_tclk_r == JtagOpRead) begin
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
                        select_AXISeriesDataWithErrorStatus_i;
          series_request_fifo_din_tclk_d.data                            = data_val;
          series_request_fifo_din_tclk_d.increment_addr                  = incr_addr_bit;

          if (is_plain_read) begin
            plain_reads_pending_tclk_d = plain_reads_pending_tclk_d + 1'b1;
            series_reads_pushed_tclk_d = series_reads_pushed_tclk_d + 1'b1;
          end

          if (select_AXISeriesDataWithErrorStatus_i) begin
            series_errstat_pending_tclk_d = 1'b1;
          end
        end else if (!can_accept) begin
          // True backpressure: FIFO full or AXI in-flight bound
          // hit. Surface to host via sticky_full. Errstat
          // captures also record BUSY_OR_FULL on the single-op
          // status path.
          sticky_axi_status_full_tclk_d = 1'b1;
          if (select_AXISeriesDataWithErrorStatus_i) begin
            last_single_op_status_tclk_d  = CaptureStatusBusyOrFull;
            series_errstat_pending_tclk_d = 1'b0;
          end
        end
        // else (!budget_ok): silent drop, see comment above.
      end
    end

    // Read pipeline preload decrement on capture (TCK-local)
    if (capture_en_i && (select_AXISeriesDataIncr_i || select_AXISeriesDataNoIncr_i) &&
            (series_ctrl_op_mode_tclk_r == JtagOpRead)) begin
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

    // The series status holds the first series error until
    // AXI_SERIES_CTRL.reset, which the SERIES_CTRL update above has already
    // applied to sticky_axi_status_tclk_d. SINGLE_OP completions report only
    // through the SINGLE_OP status.
    series_status_takes_completion = !current_tx_is_from_single_buffer_tclk &&
                                     (sticky_axi_status_tclk_d == CaptureStatusSuccess);

    // FSM completion status updates (write response path).
    if (fsm_updates_bresp_status_tclk_comb) begin
      if (series_status_takes_completion) begin
        sticky_axi_status_tclk_d = next_status_tclk_comb;
      end
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
      if (series_status_takes_completion) begin
        sticky_axi_status_tclk_d = next_status_tclk_comb;
      end
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

  always_ff @(posedge tck_i or negedge trst_ni) begin
    if (!trst_ni) begin
      single_tx_req_valid_tclk          <= 1'b0;
      single_tx_op_tclk                 <= JtagOpNop;
      single_tx_addr_tclk               <= '0;
      single_tx_data_tclk               <= '0;
      single_tx_axi_size_tclk           <= '0;
      single_tx_wstrb_tclk              <= '0;

      series_ctrl_size_tclk_r           <= '0;
      series_ctrl_pipeline_depth_tclk_r <= '0;
      series_ctrl_address_tclk_r        <= '0;
      series_ctrl_op_mode_tclk_r        <= JtagOpNop;

      single_op_pending_tclk            <= 1'b0;
      series_errstat_pending_tclk       <= 1'b0;
      last_single_op_status_tclk        <= CaptureStatusSuccess;
      last_read_data_tclk               <= '0;
      last_single_op_was_read_tclk      <= 1'b0;
      sticky_axi_status_tclk            <= CaptureStatusSuccess;
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

    if (select_AXISingleOp_i) begin
      if (single_op_pending_tclk) begin
        capture_data_tclk[AxiSingleOpOpHigh:AxiSingleOpOpLow] = CaptureStatusBusyOrFull;
      end else begin
        capture_data_tclk[AxiSingleOpOpHigh:AxiSingleOpOpLow] = last_single_op_status_tclk;
      end

      if (last_single_op_was_read_tclk) begin
        if (single_op_pending_tclk) begin
          capture_data_tclk[AxiSingleOpDataHigh:AxiSingleOpDataLow] = RDATA_PENDING_VALUE_CONST;
        end else begin
          capture_data_tclk[AxiSingleOpDataHigh:AxiSingleOpDataLow] = last_read_data_tclk;
        end
      end else begin
        capture_data_tclk[AxiSingleOpDataHigh:AxiSingleOpDataLow] = single_op_data_tclk;
      end

      capture_data_tclk[AxiSingleOpSizeHigh:AxiSingleOpSizeLow]   = single_op_size_tclk;
      capture_data_tclk[AxiSingleOpWstrbHigh:AxiSingleOpWstrbLow] = single_op_wstrb_tclk;
      capture_data_tclk[AxiSingleOpAddrHigh:AxiSingleOpAddrLow]   = single_op_addr_tclk;

    end else if (select_AXISeriesCtrl_i) begin
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
        capture_data_tclk[AxiSeriesCtrlOpHigh:AxiSeriesCtrlOpLow] = CaptureStatusBusyOrFull;
      end else begin
        capture_data_tclk[AxiSeriesCtrlOpHigh:AxiSeriesCtrlOpLow] = sticky_axi_status_tclk;
      end
      capture_data_tclk[AxiSeriesCtrlSizeHigh:AxiSeriesCtrlSizeLow] = series_ctrl_size_tclk_r;
      capture_data_tclk[AxiSeriesCtrlPdHigh:AxiSeriesCtrlPdLow]     = series_ctrl_pipeline_depth_tclk_r;
      capture_data_tclk[AxiSeriesCtrlAddrHigh:AxiSeriesCtrlAddrLow] = visible_addr;
      capture_data_tclk[AxiSeriesCtrlResetHigh] = 1'b0;

    end else if (select_AXISeriesDataIncr_i || select_AXISeriesDataNoIncr_i) begin
      automatic int mapped_len_for_capture_local;
      automatic int num_bytes_to_copy;

      mapped_len_for_capture_local = size_to_bits(3'(latched_series_size_for_len_tclk));
      if (mapped_len_for_capture_local > DATA_WIDTH) mapped_len_for_capture_local = DATA_WIDTH;
      num_bytes_to_copy = mapped_len_for_capture_local >> 3;  // bits-to-bytes: divide by 8

      if (series_ctrl_op_mode_tclk_r == JtagOpRead) begin
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
        if ((series_read_preload_count_tclk == 0) && !series_rsp_fifo_empty_tclk && capture_en_i) begin
          series_rsp_fifo_pop_tclk = 1'b1;
        end
      end else begin
        for (int byte_idx = 0; byte_idx < DATA_WIDTH / 8; byte_idx++) begin
          if (byte_idx < num_bytes_to_copy) begin
            capture_data_tclk[byte_idx*8+:8] = series_data_val_tclk[byte_idx*8+:8];
          end
        end
      end

    end else if (select_AXISeriesDataWithErrorStatus_i) begin
      automatic logic [$clog2(SharedSrLen+1)-1:0] mapped_data_bits_cap_local;
      automatic int num_bytes_to_copy;
      automatic logic[DATA_WIDTH-1:0] capture_value_data_local;
      automatic logic [1:0] captured_op_status_local;

      mapped_data_bits_cap_local = size_to_bits(3'(latched_series_size_for_len_tclk));
      if (mapped_data_bits_cap_local > DATA_WIDTH) mapped_data_bits_cap_local = DATA_WIDTH;
      num_bytes_to_copy = int'(mapped_data_bits_cap_local) >> 3;  // bits-to-bytes: divide by 8

      if (series_ctrl_op_mode_tclk_r == JtagOpRead) begin
        if (series_errstat_pending_tclk) begin
          capture_value_data_local = RDATA_PENDING_VALUE_CONST;
          captured_op_status_local = CaptureStatusBusyOrFull;
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

      if (mapped_data_bits_cap_local < SharedSrLen) begin
        if (series_errstat_pending_tclk) begin
          capture_data_tclk[mapped_data_bits_cap_local] = 1'b1;  // Busy
        end else begin
          if (captured_op_status_local == CaptureStatusSuccess) begin
            capture_data_tclk[mapped_data_bits_cap_local] = 1'b0;
          end else begin
            capture_data_tclk[mapped_data_bits_cap_local] = 1'b1;
          end
        end
      end
    end
  end

endmodule : jtag2axi
