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

  localparam int unsigned REG_ADDR_WIDTH = log_engine_reg_pkg::LOG_ENGINE_REG_MIN_ADDR_WIDTH;
  localparam int unsigned REG_DATA_WIDTH = 32;
  localparam int unsigned REG_STRB_WIDTH = REG_DATA_WIDTH / 8;

  typedef logic [REG_ADDR_WIDTH-1:0] reg_addr_t;
  typedef logic [REG_DATA_WIDTH-1:0] reg_data_t;
  typedef logic [REG_STRB_WIDTH-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(csr_axil, reg_addr_t, reg_data_t, reg_strb_t)


  /////////////////////////////////////
  // Log Fetch Interface Definitions //
  /////////////////////////////////////

  localparam int unsigned LOG_FETCH_ADDR_WIDTH = 56;
  localparam int unsigned LOG_FETCH_DATA_WIDTH = 64;
  localparam int unsigned LOG_FETCH_STRB_WIDTH = LOG_FETCH_DATA_WIDTH / 8;

  typedef logic [LOG_FETCH_ADDR_WIDTH-1:0] log_fetch_addr_t;
  typedef logic [LOG_FETCH_DATA_WIDTH-1:0] log_fetch_data_t;
  typedef logic [LOG_FETCH_STRB_WIDTH-1:0] log_fetch_strb_t;

  `AXI_LITE_TYPEDEF_ALL(log_fetch_axil, log_fetch_addr_t, log_fetch_data_t, log_fetch_strb_t)


  /////////////////////////////////////
  // Log Write Interface Definitions //
  /////////////////////////////////////

  localparam int unsigned LOG_WRITE_ADDR_WIDTH = 32;
  localparam int unsigned LOG_WRITE_DATA_WIDTH = 32;
  localparam int unsigned LOG_WRITE_STRB_WIDTH = LOG_WRITE_DATA_WIDTH / 8;

  typedef logic [LOG_WRITE_ADDR_WIDTH-1:0] log_write_addr_t;
  typedef logic [LOG_WRITE_DATA_WIDTH-1:0] log_write_data_t;
  typedef logic [LOG_WRITE_STRB_WIDTH-1:0] log_write_strb_t;

  // Always emit AXI-Lite types — used internally by log_engine and by the testbench
  // adapter (when CSR is APB) to bridge to an AXI-Lite memory model.
  `AXI_LITE_TYPEDEF_ALL(log_write_axil, log_write_addr_t, log_write_data_t, log_write_strb_t)


  ////////////////////////////
  // Log Engine Definitions //
  ////////////////////////////

  // Independent Parameters
  localparam int unsigned NUM_LOG_ENTRIES = 16;  // Must be a power of 2.
  localparam int unsigned MAX_LOG_REGION_SIZE = 524288;  // 512 KB.
  localparam int unsigned LOG_REGION_ALIGNMENT = NUM_LOG_ENTRIES * (LOG_FETCH_DATA_WIDTH / 8);

  // Dependent Parameters
  // General parameters
  typedef log_engine_reg_pkg::log_engine__LOG_REGION_SIZE__LOG_REGION_SIZE__out_t log_region_size_field_t;
  localparam log_region_size_field_t LOG_REGION_SIZE_FIELD = '{default: '0};
  localparam int unsigned LOG_REGION_SIZE_W = $bits(LOG_REGION_SIZE_FIELD.value);
  typedef logic [LOG_REGION_SIZE_W-1:0] log_region_size_t;

  localparam int unsigned MAX_LOG_LEN = MAX_LOG_REGION_SIZE / NUM_LOG_ENTRIES;
  localparam int unsigned LOG_LEN_WIDTH = $clog2(MAX_LOG_LEN + 1);
  typedef logic [LOG_LEN_WIDTH-1:0] log_len_t;

  localparam int unsigned LOG_INDEX_WIDTH = NUM_LOG_ENTRIES > 1 ? $clog2(NUM_LOG_ENTRIES) : 1;
  typedef logic [LOG_INDEX_WIDTH-1:0] log_index_t;

  // Log fetch parameters
  typedef logic [7:0] byte_t;
  localparam int unsigned LOG_WORD_SIZE = LOG_FETCH_DATA_WIDTH / 8;
  typedef byte_t [LOG_WORD_SIZE-1:0] log_word_t;

  function automatic log_len_t log_word_floor(input log_len_t byte_count);
    return (byte_count / log_len_t'(LOG_WORD_SIZE)) * log_len_t'(LOG_WORD_SIZE);
  endfunction

  localparam int unsigned LOG_WORD_BYTE_PTR_WIDTH = $clog2(LOG_WORD_SIZE);
  typedef logic [LOG_WORD_BYTE_PTR_WIDTH-1:0] log_word_byte_ptr_t;

  localparam int unsigned LOG_WORDS_FETCHED_CNT_WIDTH = $clog2((MAX_LOG_LEN / LOG_WORD_SIZE) + 1);
  typedef logic [LOG_WORDS_FETCHED_CNT_WIDTH-1:0] log_words_fetched_cnt_t;

  // Log write parameters
  localparam int unsigned LOG_BYTES_WRITTEN_CNT_WIDTH = LOG_LEN_WIDTH;
  typedef logic [LOG_BYTES_WRITTEN_CNT_WIDTH-1:0] log_bytes_written_cnt_t;


  /////////////////////
  // FSM Definitions //
  /////////////////////

  typedef enum logic [1:0] {
    ST_LOG_FETCH_IDLE = 2'd0,
    ST_LOG_FETCH_REQ  = 2'd1,
    ST_LOG_FETCH_WAIT = 2'd2
  } log_fetch_fsm_state_t;

  typedef enum logic [1:0] {
    ST_LOG_WRITE_IDLE = 2'd0,
    ST_LOG_WRITE_REQ  = 2'd1,
    ST_LOG_WRITE_WAIT = 2'd2
  } log_write_fsm_state_t;

endpackage
