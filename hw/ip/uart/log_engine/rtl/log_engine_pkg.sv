// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define AXI-Lite typedefs and constants for the log engine.
//
// Types the CSR port (register-block minimum address width, 32-bit data), the log-fetch port
// (56-bit address, 64-bit data) and the log-write port (32-bit address and data).
// Also defines the 16-entry log ring, the 512 KiB maximum log region and its alignment,
// the derived length, index and counter types, and the fetch and write FSM states.

package log_engine_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned RegAddrWidth = log_engine_reg_pkg::LOG_ENGINE_REG_MIN_ADDR_WIDTH;
  localparam int unsigned RegDataWidth = 32;
  localparam int unsigned RegStrbWidth = RegDataWidth / 8;

  typedef logic [RegAddrWidth-1:0] reg_addr_t;
  typedef logic [RegDataWidth-1:0] reg_data_t;
  typedef logic [RegStrbWidth-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(csr_axil, reg_addr_t, reg_data_t, reg_strb_t)


  /////////////////////////////////////
  // Log Fetch Interface Definitions //
  /////////////////////////////////////

  localparam int unsigned LogFetchAddrWidth = 56;
  localparam int unsigned LogFetchDataWidth = 64;
  localparam int unsigned LogFetchStrbWidth = LogFetchDataWidth / 8;

  typedef logic [LogFetchAddrWidth-1:0] log_fetch_addr_t;
  typedef logic [LogFetchDataWidth-1:0] log_fetch_data_t;
  typedef logic [LogFetchStrbWidth-1:0] log_fetch_strb_t;

  `AXI_LITE_TYPEDEF_ALL(log_fetch_axil, log_fetch_addr_t, log_fetch_data_t, log_fetch_strb_t)


  /////////////////////////////////////
  // Log Write Interface Definitions //
  /////////////////////////////////////

  localparam int unsigned LogWriteAddrWidth = 32;
  localparam int unsigned LogWriteDataWidth = 32;
  localparam int unsigned LogWriteStrbWidth = LogWriteDataWidth / 8;

  typedef logic [LogWriteAddrWidth-1:0] log_write_addr_t;
  typedef logic [LogWriteDataWidth-1:0] log_write_data_t;
  typedef logic [LogWriteStrbWidth-1:0] log_write_strb_t;

  // Always emit AXI-Lite types — used internally by log_engine and by the testbench
  // adapter (when CSR is APB) to bridge to an AXI-Lite memory model.
  `AXI_LITE_TYPEDEF_ALL(log_write_axil, log_write_addr_t, log_write_data_t, log_write_strb_t)


  ////////////////////////////
  // Log Engine Definitions //
  ////////////////////////////

  // Independent Parameters
  localparam int unsigned NumLogEntries = 16;  // Must be a power of 2.
  localparam int unsigned MaxLogRegionSize = 524288;  // 512 KB.
  localparam int unsigned LogRegionAlignment = NumLogEntries * (LogFetchDataWidth / 8);

  // Dependent Parameters
  // General parameters
  localparam int unsigned LogRegionSizeW = $bits(
      log_engine_reg_pkg::log_engine__LOG_REGION_SIZE__LOG_REGION_SIZE__out_t
  );
  typedef logic [LogRegionSizeW-1:0] log_region_size_t;

  localparam int unsigned MaxLogLen = MaxLogRegionSize / NumLogEntries;
  localparam int unsigned LogLenWidth = $clog2(MaxLogLen + 1);
  typedef logic [LogLenWidth-1:0] log_len_t;

  localparam int unsigned LogIndexWidth = NumLogEntries > 1 ? $clog2(NumLogEntries) : 1;
  typedef logic [LogIndexWidth-1:0] log_index_t;

  // Log fetch parameters
  typedef logic [7:0] byte_t;
  localparam int unsigned LogWordSize = LogFetchDataWidth / 8;
  typedef byte_t [LogWordSize-1:0] log_word_t;

  function automatic log_len_t log_word_floor(input log_len_t byte_count);
    return (byte_count / log_len_t'(LogWordSize)) * log_len_t'(LogWordSize);
  endfunction

  localparam int unsigned LogWordBytePtrWidth = $clog2(LogWordSize);
  typedef logic [LogWordBytePtrWidth-1:0] log_word_byte_ptr_t;

  localparam int unsigned LogWordsFetchedCntWidth = $clog2((MaxLogLen / LogWordSize) + 1);
  typedef logic [LogWordsFetchedCntWidth-1:0] log_words_fetched_cnt_t;

  // Log write parameters
  localparam int unsigned LogBytesWrittenCntWidth = LogLenWidth;
  typedef logic [LogBytesWrittenCntWidth-1:0] log_bytes_written_cnt_t;


  /////////////////////
  // FSM Definitions //
  /////////////////////

  typedef enum logic [1:0] {
    ST_LOG_FETCH_IDLE = 2'd0,
    ST_LOG_FETCH_REQ  = 2'd1,
    ST_LOG_FETCH_WAIT = 2'd2
  } log_fetch_fsm_state_e;

  typedef enum logic [1:0] {
    ST_LOG_WRITE_IDLE = 2'd0,
    ST_LOG_WRITE_REQ  = 2'd1,
    ST_LOG_WRITE_WAIT = 2'd2
  } log_write_fsm_state_e;

endpackage
