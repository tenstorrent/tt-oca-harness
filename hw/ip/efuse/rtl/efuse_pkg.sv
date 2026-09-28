// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define shared eFuse field-map rules, shadow range maps, and bus typedef helpers.
//
// Provides rule_t, shadow_word_range_map_t, and related constants imported by the
// controller, guard, shadow regs, and token processing.
// Also defines the lifecycle-state encoding, fuse commands, and address-decode selects, and
// includes the AXI, APB, and fuse-command typedef macros used by interface blocks.

package efuse_pkg;

  `include "axi/typedef.svh"

  `include "apb/typedef.svh"
  `include "efuse_typedef.svh"

  // Physical OTP bits allocated to the LOCK field
  localparam int unsigned LOCK_FIELD_BIT_WIDTH = 96;
  localparam int unsigned EFUSE_FIELD_MAP_IDX_WIDTH = $clog2(LOCK_FIELD_BIT_WIDTH / 2);

  //////////////////////////////
  // Register Map Definitions //
  //////////////////////////////

  localparam int unsigned NUM_END_POINTS_DECODE = 2;
  typedef enum logic [$clog2(
NUM_END_POINTS_DECODE
)-1:0] {
    INTERFACE_SEL         = 1'd0,
    SHIM_SEL              = 1'd1
  } efuse_req_decode_select_e;

  localparam int unsigned NUM_END_POINTS_REG = 4;
  typedef enum logic [$clog2(
NUM_END_POINTS_REG
)-1:0] {
    SHADOW_REG_MAP              = 2'd0,
    EFUSE_CSR_REG_MAP           = 2'd1,
    EFUSE_MMR_REG_MAP           = 2'd2,
    ERR_DECODE                  = 2'd3
  } efuse_reg_map_e;

  //////////////////////////////
  // JTAG Tap Parameters      //
  //////////////////////////////

  localparam int unsigned TDR_WIDTH = 32;
  typedef logic [TDR_WIDTH-1:0] tdr_t;

  //////////////////////////////
  // LC State Encoding        //
  //////////////////////////////

  localparam int unsigned LC_STATE_RAW_WIDTH = 4;

  typedef enum logic [LC_STATE_RAW_WIDTH-1:0] {
    LC_TEST_DEV    = 4'b0000,
    LC_PROD        = 4'b0001,
    LC_RMA_SIP_0   = 4'b0010,
    LC_RMA_SIP_1   = 4'b0011,
    LC_RMA_CHIP_0  = 4'b0110,
    LC_RMA_CHIP_1  = 4'b0111,
    LC_PROD_END    = 4'b1000
  } lc_state_raw_e;

  // Returns 1 iff s is outside the LC_STATE encodings
  function automatic logic is_invalid_lc_state(logic [LC_STATE_RAW_WIDTH-1:0] s);
    return !(s inside {LC_TEST_DEV, LC_PROD, LC_RMA_SIP_0, LC_RMA_SIP_1,
                         LC_RMA_CHIP_0, LC_RMA_CHIP_1, LC_PROD_END});
  endfunction

  //////////////////////////////
  // Shadow Register Indices  //
  //////////////////////////////

  // Shadow-register word indices (32-bit words from address 0).
  // LOCKS (64-bit) occupies words 0-1, LOCKS_SPARE (32-bit) word 2.
  // LC_STATE at byte offset 0xC is word 3, TRANSIENT_RMA_EN at 0x14 is word 5.
  localparam int unsigned SHADOW_IDX_LC_STATE = 3;
  localparam int unsigned SHADOW_IDX_TRANSIENT_RMA_EN = 5;

  localparam int unsigned MAX_CLASS1_SHADOW_RANGES = 10;

  typedef struct packed {
    logic        valid;
    logic [31:0] first_word;
    logic [31:0] last_word;
  } shadow_word_range_t;

  typedef shadow_word_range_t [MAX_CLASS1_SHADOW_RANGES-1:0] shadow_word_range_map_t;

  function automatic shadow_word_range_t make_shadow_word_range(
      input int unsigned register_offset_bytes, input int unsigned register_width_bits,
      input int unsigned shadow_word_width_bits);
    shadow_word_range_t range_cfg;
    int unsigned word_count;
    range_cfg.valid = 1'b1;
    range_cfg.first_word =
            register_offset_bytes / (shadow_word_width_bits / 8);
    word_count =
            (register_width_bits + shadow_word_width_bits - 1) /
            shadow_word_width_bits;
    range_cfg.last_word = range_cfg.first_word + word_count - 1;
    return range_cfg;
  endfunction

  function automatic int unsigned shadow_range_word_count(input shadow_word_range_t range_cfg);
    if (range_cfg.valid) begin
      return range_cfg.last_word - range_cfg.first_word + 1;
    end
    return 0;
  endfunction

  function automatic int unsigned shadow_range_map_word_count(
      input shadow_word_range_map_t range_map);
    int unsigned word_count;
    word_count = 0;
    for (int unsigned i = 0; i < MAX_CLASS1_SHADOW_RANGES; i++) begin
      word_count += shadow_range_word_count(range_map[i]);
    end
    return word_count;
  endfunction

  function automatic logic shadow_range_map_contains_word(input shadow_word_range_map_t range_map,
                                                          input int unsigned word_idx);
    logic contains_word;
    contains_word = 1'b0;
    for (int unsigned i = 0; i < MAX_CLASS1_SHADOW_RANGES; i++) begin
      if (range_map[i].valid &&
                (word_idx >= range_map[i].first_word) &&
                (word_idx <= range_map[i].last_word)) begin
        contains_word = 1'b1;
      end
    end
    return contains_word;
  endfunction

  function automatic int unsigned class1_shadow_storage_idx(input shadow_word_range_map_t range_map,
                                                            input int unsigned word_idx);
    int unsigned storage_idx;
    storage_idx = 0;
    for (int unsigned i = 0; i < MAX_CLASS1_SHADOW_RANGES; i++) begin
      if (range_map[i].valid && (word_idx > range_map[i].last_word)) begin
        storage_idx += shadow_range_word_count(range_map[i]);
      end else if (range_map[i].valid && (word_idx >= range_map[i].first_word)) begin
        storage_idx += word_idx - range_map[i].first_word;
      end
    end
    return storage_idx;
  endfunction

  function automatic int unsigned normal_shadow_storage_idx(input shadow_word_range_map_t range_map,
                                                            input int unsigned word_idx);
    int unsigned storage_idx;
    storage_idx = word_idx;
    for (int unsigned i = 0; i < MAX_CLASS1_SHADOW_RANGES; i++) begin
      if (range_map[i].valid && (word_idx > range_map[i].last_word)) begin
        storage_idx -= shadow_range_word_count(range_map[i]);
      end
    end
    return storage_idx;
  endfunction

  function automatic logic shadow_range_map_is_valid(input shadow_word_range_map_t range_map,
                                                     input int unsigned num_shadow_words);
    logic map_is_valid;
    map_is_valid = 1'b1;
    for (int unsigned i = 0; i < MAX_CLASS1_SHADOW_RANGES; i++) begin
      if (range_map[i].valid &&
                ((range_map[i].first_word > range_map[i].last_word) ||
                 (range_map[i].last_word >= num_shadow_words))) begin
        map_is_valid = 1'b0;
      end
      for (int unsigned j = i + 1; j < MAX_CLASS1_SHADOW_RANGES; j++) begin
        if (range_map[i].valid && range_map[j].valid &&
                    !((range_map[i].last_word < range_map[j].first_word) ||
                      (range_map[j].last_word < range_map[i].first_word))) begin
          map_is_valid = 1'b0;
        end
      end
    end
    return map_is_valid;
  endfunction

  //////////////////////////////
  // Fuse Command Parameters  //
  //////////////////////////////

  typedef enum logic [1:0] {
    FUSE_COMMAND_READ = 2'b00,
    FUSE_COMMAND_PROGRAM = 2'b01,
    FUSE_COMMAND_PROGRAM_READ_BACK = 2'b10
  } fuse_command_e;

  typedef struct packed {
    logic [EFUSE_FIELD_MAP_IDX_WIDTH - 1:0] idx;
    logic [3:0] lock;
    logic [31:0] start_addr;
    logic [31:0] end_addr;
  } rule_t;

endpackage
