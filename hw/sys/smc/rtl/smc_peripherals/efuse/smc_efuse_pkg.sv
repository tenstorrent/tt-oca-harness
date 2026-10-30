// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare types and constants for the SMC eFuse map.
//
// Sizes the 8192-bit fuse array as 256 32-bit words and defines efuse_map_t, the
// shadow-register layout of the SMC eFuse map, together with the fuse command types.
// Builds EfuseFieldMap, the per-field lock rules and address ranges, and the Class 1
// shadow range that covers the HARNESS_LOCKS and ADOPTER_LOCKS fields. Used by smc_efuse_wrapper and by the SMC
// ports that carry the shadow registers and fuse commands.

package smc_efuse_pkg;

  function automatic int unsigned efuse_offset(input longint unsigned addr);
    return int'(addr - smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR);
  endfunction

  // Shadow register layout preserved from the legacy generated sub-block header.
  typedef struct packed {
    logic [0:0]   spare_tail_read_lock ;
    logic [0:0]   spare_tail_write_lock ;
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
  } smc_efuse_map_harness_locks_reg_t;

  typedef struct packed {
    logic [0:0]   read_lock ;
    logic [0:0]   write_lock ;
  } smc_efuse_map_adopter_lock_pair_t;

  typedef struct packed {
    smc_efuse_map_adopter_lock_pair_t [31:0] region;
  } smc_efuse_map_adopter_locks_reg_t;

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



  typedef struct packed {logic [63:0] rsvd;} smc_efuse_map_spare_tail_reg_t;

  typedef struct packed {
    smc_efuse_map_spare_tail_reg_t [2:0] spare_tail;
    smc_efuse_map_spare_reg_t [26:0] spare;
    smc_efuse_map_occp_transport_timeout_reg_t occp_transport_timeout;
    smc_efuse_map_smc_config_reg_t smc_config;
    smc_efuse_map_i2c_i3c_id_reg_t [8:0] i2c_i3c_id;
    smc_efuse_map_jtag_public_identity_reg_t jtag_public_identity;
    smc_efuse_map_adopter_locks_reg_t adopter_locks;
    smc_efuse_map_harness_locks_reg_t harness_locks;
  } smc_efuse_map_regmap_t;
  `include "efuse_typedef.svh"

  // NumFuseWordWidth MAX is 32 bits
  localparam int unsigned NumEfuseBits = 8 * 1024;  // 8192 bits.
  localparam int unsigned NumFuseWordWidth = 32;

  localparam int unsigned NumFuseWords = NumEfuseBits / NumFuseWordWidth; // 256 words --- word == access granularity.
  localparam int unsigned NumFuseBytes = NumFuseWords * 4;  // 1024 bytes.

  // The adopter fuse region follows the harness map in the fuse address space and is capped
  // by its window in smc_external, so fuse commands must address and count both.
  localparam int unsigned MaxAdopterFuseWords =
      int'(smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_ADOPTER_FUSE_SIZE) / 4;
  localparam int unsigned MaxSenseWords = NumFuseWords + MaxAdopterFuseWords;

  localparam int unsigned NumFuseBitsWidth = $clog2(
      MaxSenseWords * NumFuseWordWidth
  );  // 16 bits to encode the harness bank and the largest adopter region
  localparam int unsigned NumFuseByteWidth = $clog2(
      NumFuseBytes
  );  // 10 bits to encode 1024 bytes <- used to create byte address type for bank
  // NOTE: $clog2(N) can only represent 0 to N-1, but a full-length read counts N words
  localparam int unsigned NumFuseWordsWidth = $clog2(MaxSenseWords + 1);
  localparam int unsigned ShadowRegBits = NumEfuseBits;

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

  // Lock meta-field + 4 functional fields + NumSpareRegions spare regions + SPARE_TAIL
  // (idx 0-31).
  localparam int unsigned NumEfuseFields = 6 + NumSpareRegions;
  localparam logic [efuse_pkg::EfuseFieldMapIdxWidth-1:0] LocksMetaIdx = '1;
  localparam logic [1:0] WriteUnlock = 2'b00;
  localparam logic [1:0] WriteSetOnly = 2'b10;
  localparam logic [1:0] WriteLock = 2'b11;
  localparam logic ReadUnlock = 1'b0;
  localparam logic ReadLock = 1'b1;

  // Physical OTP bits covered by HARNESS_LOCKS and ADOPTER_LOCKS
  localparam int unsigned LockFieldBits = $bits(smc_efuse_map_harness_locks_reg_t);
  localparam int unsigned AdopterLockFieldBits = $bits(smc_efuse_map_adopter_locks_reg_t);

  typedef struct packed {
    logic [NumEfuseBits-LockFieldBits-AdopterLockFieldBits-1:0] reserved;
    logic [AdopterLockFieldBits-1:0]                            adopter_locks;
    logic [LockFieldBits-1:0]                                   locks;
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
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_HARNESS_LOCKS_BASE_ADDR
          ),
          LockFieldBits + AdopterLockFieldBits,
          NumFuseWordWidth
      ),
      default: '0
  };

  // Lock field Description
  // lock[2:1] write: 00 -> unlock;11 -> lock ;10 -> set only;
  // lock[0]  read: 0 -> readable; 1 -> read locked
  function automatic efuse_pkg::rule_t [NumEfuseFields-1:0] build_efuse_field_map();
    efuse_pkg::rule_t [NumEfuseFields-1:0] map;

    // HARNESS_LOCKS and ADOPTER_LOCKS; hardware never applies lock bits to this entry.
    map[0] = '{
        idx: LocksMetaIdx,
        lock: {WriteSetOnly, ReadUnlock},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_HARNESS_LOCKS_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR)-1
    };
    map[1] = '{ // JTAG_PUBLIC_IDENTITY (idx 0)
        idx: 6'd0,
        lock: {WriteUnlock, ReadUnlock},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0))-1
    };
    map[2] = '{ // I2C_I3C_ID[9] -- all nine elements share one slot (idx 1)
        idx: 6'd1,
        lock: {WriteUnlock, ReadUnlock},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0)),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR)-1
    };
    map[3] = '{ // SMC_CONFIG (idx 2)
        idx: 6'd2,
        lock: {WriteUnlock, ReadUnlock},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR)-1
    };
    map[4] = '{ // OCCP_TRANSPORT_TIMEOUT (idx 3)
        idx: 6'd3,
        lock: {WriteUnlock, ReadUnlock},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR),
        end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(0))-1
    };

    // SPARE[0..NumSpareRegions-1] take slots 4 onwards, one each.
    for (int unsigned k = 0; k < NumSpareRegions; k++) begin
      map[5+k] = '{
          idx: efuse_pkg::EfuseFieldMapIdxWidth'(4 + k),
          lock: {WriteUnlock, ReadUnlock},
          start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(k)),
          end_addr:
          (
          k == NumSpareRegions - 1
          ) ?
          (efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_TAIL_BASE_ADDR(0)) - 1)
          : (
          efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(k + 1)) - 1
          )
      };
    end
    map[5+NumSpareRegions] = '{ // SPARE_TAIL[3] -- all three elements share the last slot
        idx: efuse_pkg::EfuseFieldMapIdxWidth'(4 + NumSpareRegions),
        lock: {WriteUnlock, ReadUnlock},
        start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SPARE_TAIL_BASE_ADDR(0)),
        end_addr: int'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SIZE) - 1
    };

    return map;
  endfunction

  localparam efuse_pkg::rule_t [NumEfuseFields-1:0] EfuseFieldMap = build_efuse_field_map();

  // One adopter lock region per ADOPTER_LOCKS pair.
  localparam int unsigned AdopterLockRegions = AdopterLockFieldBits / 2;
  typedef logic [AdopterLockRegions-1:0][15:0] adopter_lock_region_end_t;

  // Region n covers adopter words [region_end[n-1], region_end[n]), with region_end[-1] = 0,
  // as byte offsets in the adopter window. An entry of 0 marks an unused region: it matches no
  // address and carries the never-locked sentinel idx.
  function automatic efuse_pkg::rule_t [AdopterLockRegions-1:0] build_adopter_field_map(
      adopter_lock_region_end_t region_end);
    efuse_pkg::rule_t [AdopterLockRegions-1:0] map;
    int unsigned start_word;

    start_word = 0;
    for (int unsigned n = 0; n < AdopterLockRegions; n++) begin
      if (region_end[n] != '0) begin
        map[n] = '{
            idx: efuse_pkg::EfuseFieldMapIdxWidth'(n),
            lock: {WriteUnlock, ReadUnlock},
            start_addr: 4 * start_word,
            end_addr: 4 * int'(region_end[n]) - 1
        };
        start_word = int'(region_end[n]);
      end else begin
        map[n] = '{idx: LocksMetaIdx, lock: '0, start_addr: '1, end_addr: '0};
      end
    end
    return map;
  endfunction

endpackage
