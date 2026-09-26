// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare types and constants for the SMC eFuse shim.
//
// Describes the vendor eFuse CSR window carved from smc_external.
// Shared by smc_efuse_wrapper and the peripheral AXI-Lite address map.

package smc_efuse_pkg;
  import smc_top_addrmap_pkg::*;

  function automatic int unsigned efuse_offset(input longint unsigned addr);
    return int'(addr - smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR);
  endfunction

  // Shadow register layout preserved from the legacy generated sub-block header.
  typedef struct packed {
    logic [0:0]   spare27_read_lock ;
    logic [0:0]   spare27_write_lock ;
    logic [0:0]   spare26_read_lock ;
    logic [0:0]   spare26_write_lock ;
    logic [0:0]   spare25_read_lock ;
    logic [0:0]   spare25_write_lock ;
    logic [0:0]   spare24_read_lock ;
    logic [0:0]   spare24_write_lock ;
    logic [0:0]   spare23_read_lock ;
    logic [0:0]   spare23_write_lock ;
    logic [0:0]   spare22_read_lock ;
    logic [0:0]   spare22_write_lock ;
    logic [0:0]   spare21_read_lock ;
    logic [0:0]   spare21_write_lock ;
    logic [0:0]   spare20_read_lock ;
    logic [0:0]   spare20_write_lock ;
    logic [0:0]   spare19_read_lock ;
    logic [0:0]   spare19_write_lock ;
    logic [0:0]   spare18_read_lock ;
    logic [0:0]   spare18_write_lock ;
    logic [0:0]   spare17_read_lock ;
    logic [0:0]   spare17_write_lock ;
    logic [0:0]   spare16_read_lock ;
    logic [0:0]   spare16_write_lock ;
    logic [0:0]   spare15_read_lock ;
    logic [0:0]   spare15_write_lock ;
    logic [0:0]   spare14_read_lock ;
    logic [0:0]   spare14_write_lock ;
    logic [0:0]   spare13_read_lock ;
    logic [0:0]   spare13_write_lock ;
    logic [0:0]   spare12_read_lock ;
    logic [0:0]   spare12_write_lock ;
    logic [0:0]   spare11_read_lock ;
    logic [0:0]   spare11_write_lock ;
    logic [0:0]   spare10_read_lock ;
    logic [0:0]   spare10_write_lock ;
    logic [0:0]   spare9_read_lock ;
    logic [0:0]   spare9_write_lock ;
    logic [0:0]   spare8_read_lock ;
    logic [0:0]   spare8_write_lock ;
    logic [0:0]   spare7_read_lock ;
    logic [0:0]   spare7_write_lock ;
    logic [0:0]   spare6_read_lock ;
    logic [0:0]   spare6_write_lock ;
    logic [0:0]   spare5_read_lock ;
    logic [0:0]   spare5_write_lock ;
    logic [0:0]   spare4_read_lock ;
    logic [0:0]   spare4_write_lock ;
    logic [0:0]   spare3_read_lock ;
    logic [0:0]   spare3_write_lock ;
    logic [0:0]   spare2_read_lock ;
    logic [0:0]   spare2_write_lock ;
    logic [0:0]   spare1_read_lock ;
    logic [0:0]   spare1_write_lock ;
    logic [0:0]   spare0_read_lock ;
    logic [0:0]   spare0_write_lock ;
    logic [0:0]   occp_transport_timeout_read_lock ;
    logic [0:0]   occp_transport_timeout_write_lock ;
    logic [0:0]   smc_config_read_lock ;
    logic [0:0]   smc_config_write_lock ;
    logic [0:0]   i2c_i3c_id_read_lock ;
    logic [0:0]   i2c_i3c_id_write_lock ;
    logic [0:0]   jtag_public_identity_read_lock ;
    logic [0:0]   jtag_public_identity_write_lock ;
  } smc_efuse_map_locks_reg_t;

  typedef struct packed {logic [255:0] value;} smc_efuse_map_jtag_public_identity_reg_t;

  typedef struct packed {logic [63:0] interface_id;} smc_efuse_map_i2c_i3c_id_reg_t;

  typedef struct packed {
    logic [47:0]   config_rsvd_high ;
    logic [0:0]    dft_ignore_error ;
    logic [6:0]    config_rsvd_mid ;
    logic [0:0]    sram_auto_zero_disable ;
    logic [5:0]    config_rsvd_low ;
    logic [0:0]    rom_flip_endianness ;
  } smc_efuse_map_smc_config_reg_t;



  typedef struct packed {
    logic [31:0]   timeout_rsvd ;
    logic [31:0]   timeout ;
  } smc_efuse_map_occp_transport_timeout_reg_t;



  typedef struct packed {logic [255:0] rsvd;} smc_efuse_map_spare_reg_t;



  typedef struct packed {
    smc_efuse_map_spare_reg_t [27:0] spare;
    smc_efuse_map_occp_transport_timeout_reg_t occp_transport_timeout;
    smc_efuse_map_smc_config_reg_t smc_config;
    smc_efuse_map_i2c_i3c_id_reg_t [8:0] i2c_i3c_id;
    smc_efuse_map_jtag_public_identity_reg_t jtag_public_identity;
    smc_efuse_map_locks_reg_t locks;
  } smc_efuse_map_regmap_t;
  `include "efuse_typedef.svh"

  // NumFuseWordWidth MAX is 32 bits
  localparam int unsigned NumEfuseBits = 8 * 1024;  // 8192 bits.
  localparam int unsigned NumFuseWordWidth = 32;

  localparam int unsigned NumFuseWords = NumEfuseBits / NumFuseWordWidth; // 256 words --- word == access granularity.
  localparam int unsigned NumFuseBytes = NumFuseWords * 4;  // 1024 bytes.

  localparam int unsigned NumFuseBitsWidth = $clog2(
      NumEfuseBits
  );  // 13 bits to encode 8192 bits <- used to create bit address type for bank
  localparam int unsigned NumFuseByteWidth = $clog2(
      NumFuseBytes
  );  // 10 bits to encode 1024 bytes <- used to create byte address type for bank
  // NOTE: $clog2(256)=8 can only represent 0-255, but we need to represent 256 words
  localparam int unsigned NumFuseWordsWidth = $clog2(NumFuseWords + 1);
  localparam int unsigned SHADOW_REG_BITS = NumEfuseBits;

  typedef logic [NumFuseBitsWidth-1:0] efuse_addr_bit_t;
  typedef logic [NumFuseByteWidth-1:0] efuse_addr_byte_t;
  typedef logic [NumFuseWordWidth-1:0] efuse_data_t;
  typedef logic [NumFuseWordsWidth-1:0] efuse_word_counter_t;

  // Common interface types for efuse commands and responses
  `EFUSE_COMMAND_REQ_T(fuse_command_req_t, efuse_addr_bit_t, efuse_data_t, efuse_word_counter_t,
                       efuse_pkg::fuse_command_e)
  `EFUSE_COMMAND_RESP_T(fuse_command_resp_t, efuse_data_t)

  // Spare region count follows the RDL, so adding or removing a spare region updates the field
  // count with it.
  localparam int unsigned NumSpareRegions = int'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_NUM);

  // LOCKS meta-field + 4 functional fields + NumSpareRegions spare regions (idx 0-31).
  localparam int unsigned NUM_EFUSE_FIELDS = 5 + NumSpareRegions;
  localparam logic [efuse_pkg::EFUSE_FIELD_MAP_IDX_WIDTH-1:0] LOCKS_META_IDX = '1;
  localparam logic [1:0] WRITE_UNLOCK = 2'b00;
  localparam logic [1:0] WRITE_SET_ONLY = 2'b10;
  localparam logic [1:0] WRITE_LOCK = 2'b11;
  localparam logic READ_UNLOCK = 1'b0;
  localparam logic READ_LOCK = 1'b1;

  // Physical OTP bits covered by LOCKS
  localparam int unsigned LockFieldBits = $bits(smc_efuse_map_locks_reg_t);

  typedef struct packed {
    logic [NumEfuseBits-LockFieldBits-1:0] reserved;
    logic [LockFieldBits-1:0]              locks;
  } efuse_lock_view_t;

  typedef union packed {
    smc_efuse_map_regmap_t                         fields;
    efuse_lock_view_t                              locks;
    logic [NumFuseWords-1:0][NumFuseWordWidth-1:0] values;
  } efuse_map_t;

  // Class 1 storage is selected by field identity; all locations and widths
  // are derived directly from the generated RDL metadata.
  localparam efuse_pkg::shadow_word_range_map_t Class1ShadowRanges = '{
      0:
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset(SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR), LockFieldBits, NumFuseWordWidth
      ),
      default: '0
  };

  // Lock field Description
  // lock[2:1] write: 00 -> unlock;11 -> lock ;10 -> set only;
  // lock[0]  read: 0 -> readable; 1 -> read locked
  function automatic efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] build_efuse_field_map();
    efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] map;

    // Hardware never applies lock bits to this entry.
    map[0] = '{
        idx: LOCKS_META_IDX,
        lock: {WRITE_SET_ONLY, READ_UNLOCK},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR)-1
    };
    map[1] = '{ // JTAG_PUBLIC_IDENTITY (idx 0)
        idx: 6'd0,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0))-1
    };
    map[2] = '{ // I2C_I3C_ID[9] -- all nine elements share one slot (idx 1)
        idx: 6'd1,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0)),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR)-1
    };
    map[3] = '{ // SMC_CONFIG (idx 2)
        idx: 6'd2,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR)-1
    };
    map[4] = '{ // OCCP_TRANSPORT_TIMEOUT (idx 3)
        idx: 6'd3,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(0))-1
    };

    // SPARE[0..NumSpareRegions-1] take slots 4 onwards, one each.
    for (int unsigned k = 0; k < NumSpareRegions; k++) begin
      map[5+k] = '{
          idx: efuse_pkg::EFUSE_FIELD_MAP_IDX_WIDTH'(4 + k),
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(k)),
          end_addr:
          (
          k == NumSpareRegions - 1
          ) ?
          (smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SIZE - 1)
          : (
          efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(k + 1)) - 1
          )
      };
    end

    return map;
  endfunction

  localparam efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] EfuseFieldMap = build_efuse_field_map();

endpackage
