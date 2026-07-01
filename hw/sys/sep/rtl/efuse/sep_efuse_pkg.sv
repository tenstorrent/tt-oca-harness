// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

package sep_efuse_pkg;
  import och_sep_top_addrmap_pkg::*;

  function automatic longint unsigned efuse_offset(input longint unsigned addr);
    return addr - och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR;
  endfunction

  // Shadow register layout preserved from the legacy generated sub-block header.
  typedef struct packed {
      logic [0:0]   reserved_last_32_read_lock ;
      logic [0:0]   reserved_last_32_write_lock ;
      logic [0:0]   reserved_last_64_read_lock ;
      logic [0:0]   reserved_last_64_write_lock ;
      logic [0:0]   reserved_last_256_read_lock ;
      logic [0:0]   reserved_last_256_write_lock ;
      logic [0:0]   reserved_7_read_lock ;
      logic [0:0]   reserved_7_write_lock ;
      logic [0:0]   reserved_6_read_lock ;
      logic [0:0]   reserved_6_write_lock ;
      logic [0:0]   reserved_5_read_lock ;
      logic [0:0]   reserved_5_write_lock ;
      logic [0:0]   reserved_4_read_lock ;
      logic [0:0]   reserved_4_write_lock ;
      logic [0:0]   reserved_3_read_lock ;
      logic [0:0]   reserved_3_write_lock ;
      logic [0:0]   reserved_2_read_lock ;
      logic [0:0]   reserved_2_write_lock ;
      logic [0:0]   reserved_1_read_lock ;
      logic [0:0]   reserved_1_write_lock ;
      logic [0:0]   reserved_0_read_lock ;
      logic [0:0]   reserved_0_write_lock ;
      logic [0:0]   sep_public_key_hash_1_read_lock ;
      logic [0:0]   sep_public_key_hash_1_write_lock ;
      logic [0:0]   sep_public_key_hash_0_read_lock ;
      logic [0:0]   sep_public_key_hash_0_write_lock ;
      logic [0:0]   sep_spi_ctrl_read_lock ;
      logic [0:0]   sep_spi_ctrl_write_lock ;
      logic [0:0]   sep_rom_ctrl_read_lock ;
      logic [0:0]   sep_rom_ctrl_write_lock ;
      logic [0:0]   status_rpt_read_lock ;
      logic [0:0]   status_rpt_write_lock ;
      logic [0:0]   sys_uid_read_lock ;
      logic [0:0]   sys_uid_write_lock ;
      logic [0:0]   sys_pubk_digest_read_lock ;
      logic [0:0]   sys_pubk_digest_write_lock ;
      logic [0:0]   sip_uid_read_lock ;
      logic [0:0]   sip_uid_write_lock ;
      logic [0:0]   sip_pubk_digest_read_lock ;
      logic [0:0]   sip_pubk_digest_write_lock ;
      logic [0:0]   chiplet_uid_read_lock ;
      logic [0:0]   chiplet_uid_write_lock ;
      logic [0:0]   bl2_version_read_lock ;
      logic [0:0]   bl2_version_write_lock ;
      logic [0:0]   bl1_version_read_lock ;
      logic [0:0]   bl1_version_write_lock ;
      logic [0:0]   chiplet_pubk_revoke_read_lock ;
      logic [0:0]   chiplet_pubk_revoke_write_lock ;
      logic [0:0]   class_key_read_lock ;
      logic [0:0]   class_key_write_lock ;
      logic [0:0]   rma_chiplet_token_digest_read_lock ;
      logic [0:0]   rma_chiplet_token_digest_write_lock ;
      logic [0:0]   rma_sip_token_digest_read_lock ;
      logic [0:0]   rma_sip_token_digest_write_lock ;
      logic [0:0]   sys_dis_read_lock ;
      logic [0:0]   sys_dis_write_lock ;
      logic [0:0]   sip_dis_read_lock ;
      logic [0:0]   sip_dis_write_lock ;
      logic [0:0]   transient_rma_en_read_lock ;
      logic [0:0]   transient_rma_en_write_lock ;
      logic [0:0]   sboot_dis_read_lock ;
      logic [0:0]   sboot_dis_write_lock ;
      logic [0:0]   lc_state_read_lock ;
      logic [0:0]   lc_state_write_lock ;
  } sep_efuse_map_locks_reg_t;



  typedef struct packed {
      logic [23:0]   rsvd ;
      logic [7:0]   lc_state ;
  } sep_efuse_map_lc_state_reg_t;



  typedef struct packed {
      logic [30:0]   rsvd ;
      logic [0:0]   disable_secure_boot ;
  } sep_efuse_map_sboot_dis_reg_t;



  typedef struct packed {
      logic [30:0]   rsvd ;
      logic [0:0]   transient_rma_en ;
  } sep_efuse_map_transient_rma_en_reg_t;



  typedef struct packed {
      logic [15:0]   func_reserved ;
      logic [10:0]   test_reserved ;
      logic [0:0]   ap_dtest ;
      logic [0:0]   ap_stest ;
      logic [0:0]   sep_dtest ;
      logic [0:0]   sep_stest ;
      logic [0:0]   fuse_test ;
      logic [26:0]   debug_reserved ;
      logic [0:0]   sip_debug ;
      logic [0:0]   ap_trace ;
      logic [0:0]   ap_debug ;
      logic [0:0]   soc_debug ;
      logic [0:0]   sep_debug ;
  } sep_efuse_map_lc_disable_reg_t;



  typedef struct packed {
      logic [255:0]   token_digest ;
  } sep_efuse_map_rma_sip_token_digest_reg_t;



  typedef struct packed {
      logic [255:0]   token_digest ;
  } sep_efuse_map_rma_chiplet_token_digest_reg_t;



  typedef struct packed {
      logic [255:0]   key ;
  } sep_efuse_map_class_key_reg_t;



  typedef struct packed {
      logic [31:0]   select ;
  } sep_efuse_map_chiplet_pubk_revoke_reg_t;



  typedef struct packed {
      logic [255:0]   version ;
  } sep_efuse_map_bl1_version_reg_t;



  typedef struct packed {
      logic [255:0]   version ;
  } sep_efuse_map_bl2_version_reg_t;



  typedef struct packed {
      logic [255:0]   uid ;
  } sep_efuse_map_chiplet_uid_reg_t;



  typedef struct packed {
      logic [255:0]   key_digest ;
  } sep_efuse_map_sip_pubk_digest_reg_t;



  typedef struct packed {
      logic [255:0]   uid ;
  } sep_efuse_map_sip_uid_reg_t;



  typedef struct packed {
      logic [255:0]   key_digest ;
  } sep_efuse_map_sys_pubk_digest_reg_t;



  typedef struct packed {
      logic [255:0]   uid ;
  } sep_efuse_map_sys_uid_reg_t;



  typedef struct packed {
      logic [29:0]   reserved ;
      logic [1:0]   rpt ;
  } sep_efuse_map_status_rpt_reg_t;



  typedef struct packed {
      logic [25:0]   reserved ;
      logic [4:0]   rom_swap_ctrl ;
      logic [0:0]   rom_endianness_ctrl ;
  } sep_efuse_map_sep_rom_ctrl_reg_t;



  typedef struct packed {
      logic [12:0]   spi_control_field_en_rsvd ;
      logic [10:0]   smu_pll_sysclk ;
      logic [7:0]   spi_control_field_en ;
  } sep_efuse_map_sep_spi_ctrl_field_en_reg_t;



  typedef struct packed {
      logic [31:0]   discovery ;
  } sep_efuse_map_spi_discovery_ctrl_reg_t;



  typedef struct packed {
      logic [31:0]   dq_timing ;
  } sep_efuse_map_spi_phy_dq_timing_reg_t;



  typedef struct packed {
      logic [31:0]   dqs_timing ;
  } sep_efuse_map_spi_phy_dqs_timing_reg_t;



  typedef struct packed {
      logic [31:0]   gate_lpbk ;
  } sep_efuse_map_spi_phy_gate_lpbk_reg_t;



  typedef struct packed {
      logic [31:0]   dll_slave ;
  } sep_efuse_map_spi_phy_dll_slave_reg_t;



  typedef struct packed {
      logic [31:0]   dll_master ;
  } sep_efuse_map_spi_phy_dll_master_reg_t;



  typedef struct packed {
      logic [31:0]   misc ;
  } sep_efuse_map_spi_phy_misc_reg_t;



  typedef struct packed {
      logic [31:0]   rb_valid_time ;
  } sep_efuse_map_spi_rb_valid_time_reg_t;



  typedef struct packed {
      logic [255:0]   key_hash ;
  } sep_efuse_map_public_key_reg_t;



  typedef struct packed {
      logic [511:0]   rsvd ;
  } sep_efuse_map_reserved_i_reg_t;



  typedef struct packed {
      logic [255:0]   rsvd ;
  } sep_efuse_map_reserved_last_256_reg_t;



  typedef struct packed {
      logic [63:0]   rsvd ;
  } sep_efuse_map_reserved_last_64_reg_t;



  typedef struct packed {
      logic [31:0]   rsvd ;
  } sep_efuse_map_reserved_last_32_reg_t;



  typedef struct packed {
      sep_efuse_map_reserved_last_32_reg_t reserved_last_32;
      sep_efuse_map_reserved_last_64_reg_t reserved_last_64;
      sep_efuse_map_reserved_last_256_reg_t reserved_last_256;
      sep_efuse_map_reserved_i_reg_t reserved_7;
      sep_efuse_map_reserved_i_reg_t reserved_6;
      sep_efuse_map_reserved_i_reg_t reserved_5;
      sep_efuse_map_reserved_i_reg_t reserved_4;
      sep_efuse_map_reserved_i_reg_t reserved_3;
      sep_efuse_map_reserved_i_reg_t reserved_2;
      sep_efuse_map_reserved_i_reg_t reserved_1;
      sep_efuse_map_reserved_i_reg_t reserved_0;
      sep_efuse_map_public_key_reg_t public_key_1;
      sep_efuse_map_public_key_reg_t public_key_0;
      sep_efuse_map_spi_rb_valid_time_reg_t spi_rb_valid_time;
      sep_efuse_map_spi_phy_misc_reg_t spi_phy_misc;
      sep_efuse_map_spi_phy_dll_master_reg_t spi_phy_dll_master;
      sep_efuse_map_spi_phy_dll_slave_reg_t spi_phy_dll_slave;
      sep_efuse_map_spi_phy_gate_lpbk_reg_t spi_phy_gate_lpbk;
      sep_efuse_map_spi_phy_dqs_timing_reg_t spi_phy_dqs_timing;
      sep_efuse_map_spi_phy_dq_timing_reg_t spi_phy_dq_timing;
      sep_efuse_map_spi_discovery_ctrl_reg_t spi_discovery_ctrl;
      sep_efuse_map_sep_spi_ctrl_field_en_reg_t sep_spi_ctrl_field_en;
      sep_efuse_map_sep_rom_ctrl_reg_t sep_rom_ctrl;
      sep_efuse_map_status_rpt_reg_t status_rpt;
      sep_efuse_map_sys_uid_reg_t sys_uid;
      sep_efuse_map_sys_pubk_digest_reg_t sys_pubk_digest;
      sep_efuse_map_sip_uid_reg_t sip_uid;
      sep_efuse_map_sip_pubk_digest_reg_t sip_pubk_digest;
      sep_efuse_map_chiplet_uid_reg_t chiplet_uid;
      sep_efuse_map_bl2_version_reg_t bl2_version;
      sep_efuse_map_bl1_version_reg_t bl1_version;
      sep_efuse_map_chiplet_pubk_revoke_reg_t chiplet_pubk_revoke;
      sep_efuse_map_class_key_reg_t class_key;
      sep_efuse_map_rma_chiplet_token_digest_reg_t rma_chiplet_token_digest;
      sep_efuse_map_rma_sip_token_digest_reg_t rma_sip_token_digest;
      sep_efuse_map_lc_disable_reg_t sys_dis;
      sep_efuse_map_lc_disable_reg_t sip_dis;
      sep_efuse_map_transient_rma_en_reg_t transient_rma_en;
      sep_efuse_map_sboot_dis_reg_t sboot_dis;
      sep_efuse_map_lc_state_reg_t lc_state;
      sep_efuse_map_locks_reg_t locks;
  } sep_efuse_map_regmap_t;
  `include "apb/typedef.svh"
  `include "axi/typedef.svh"
  `include "efuse_typedef.svh"

  localparam int unsigned NumEfuseBits = 8 * 1024; // 8192
  localparam int unsigned NumFuseWordWidth = 32;

  localparam int unsigned NumFuseWords = NumEfuseBits / NumFuseWordWidth; // 256
  localparam int unsigned NumFuseBytes = NumFuseWords * 4; // 1024

  localparam int unsigned NumFuseBitsWidth = $clog2(NumEfuseBits);
  localparam int unsigned NumFuseByteWidth = $clog2(NumFuseBytes);
  // NOTE: $clog2(256)=8 can only represent 0-255, but we need to represent 256 words
  // Add 1 to ensure we can hold NumFuseWords itself (not just NumFuseWords-1)
  localparam int unsigned NumFuseWordsWidth = $clog2(NumFuseWords + 1);
  localparam int unsigned SHADOW_REG_BITS = NumEfuseBits;

  typedef logic [NumFuseBitsWidth-1:0]  efuse_addr_bit_t;
  typedef logic [NumFuseByteWidth-1:0]  efuse_addr_byte_t;
  typedef logic [NumFuseWordWidth-1:0]     efuse_data_t;
  typedef logic [NumFuseWordsWidth-1:0] efuse_word_counter_t;

  // Common interface types for efuse commands and responses
  `EFUSE_COMMAND_REQ_T(fuse_command_req_t, efuse_addr_bit_t, efuse_data_t, efuse_word_counter_t, efuse_pkg::fuse_command_e)
  `EFUSE_COMMAND_RESP_T(fuse_command_resp_t, efuse_data_t)

  // AXILite interface types
  localparam int unsigned         ADDR_WIDTH = 32;
  localparam int unsigned         DATA_WIDTH = 32;
  localparam int unsigned         STRB_WIDTH = DATA_WIDTH / 8;
  typedef logic [ADDR_WIDTH    -1:0] addr_t;
  typedef logic [DATA_WIDTH    -1:0] data_t;
  typedef logic [STRB_WIDTH    -1:0] strb_t;
  `AXI_LITE_TYPEDEF_ALL(efuse_axil, addr_t, data_t, strb_t)
  `APB_TYPEDEF_ALL(efuse_apb, addr_t, data_t, strb_t)

  localparam int unsigned NUM_EFUSE_FIELDS = 31;
  localparam logic [1:0] WRITE_LOCK = 2'b11;
  localparam logic [1:0] WRITE_UNLOCK = 2'b00;
  localparam logic [1:0] WRITE_SET_ONLY = 2'b10;
  localparam logic READ_LOCK = 1'b1;
  localparam logic READ_UNLOCK = 1'b0;
  localparam logic SECURE_TM_LOCK = 1'b1;
  localparam logic SECURE_TM_UNLOCK = 1'b0;

  typedef union packed {
    sep_efuse_map_regmap_t f;
    logic [NumFuseWords-1:0][NumFuseWordWidth-1:0] values;
  } efuse_map_t;


// lock field
// lock[3]   secure_tm: 0 -> secure_tm unlock; 1 -> secure_tm lock
// lock[2:1] write: 00 -> unlock;11 -> lock ;10 -> set only;
// lock[0]   read: 0 -> readable; 1 -> read locked
  localparam efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] EfuseFieldMap = '{
    '{ // RESERVED_8
        idx: 5'd29,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_LAST_256_BASE_ADDR),
        end_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIZE - 1
    },
    '{ // RESERVED_7
        idx: 5'd28,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_7_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_LAST_256_BASE_ADDR) - 1
    },
    '{ // RESERVED_6
        idx: 5'd27,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_6_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_7_BASE_ADDR) - 1
    },
    '{ // RESERVED_5
        idx: 5'd26,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_5_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_6_BASE_ADDR) - 1
    },
    '{ // RESERVED_4
        idx: 5'd25,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_4_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_5_BASE_ADDR) - 1
    },
    '{ // RESERVED_3
        idx: 5'd24,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_3_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_4_BASE_ADDR) - 1
    },
    '{ // RESERVED_2
        idx: 5'd23,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_2_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_3_BASE_ADDR) - 1
    },
    '{ // RESERVED_1
        idx: 5'd22,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_1_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_2_BASE_ADDR) - 1
    },
    '{ // RESERVED_0
        idx: 5'd21,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_0_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_1_BASE_ADDR) - 1
    },
    '{ // PUBK_HASH_1
        idx: 5'd20,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_PUBLIC_KEY_1_BASE_ADDR),
        end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RESERVED_0_BASE_ADDR) - 1
    },
       '{ // PUBK_HASH_0
           idx: 5'd19,
           lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
           start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_PUBLIC_KEY_0_BASE_ADDR),
           end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_PUBLIC_KEY_1_BASE_ADDR) - 1
       },
      '{ // sep_spi_ctrl
          idx: 5'd18,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_PUBLIC_KEY_0_BASE_ADDR) - 1
      },
      '{ // SEP_ROM_CTRL
          idx: 5'd17,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_ROM_CTRL_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR) - 1
      },
      '{ //STATUS_RPT
          idx: 5'd16,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_STATUS_RPT_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_ROM_CTRL_BASE_ADDR) - 1
      },
      '{ //SYS_UID
          idx: 5'd15,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_UID_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_STATUS_RPT_BASE_ADDR) - 1
      },
      '{ //SYS_PUBK
          idx: 5'd14,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_DIGEST_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_UID_BASE_ADDR) - 1
      },
      '{ //SIP_UID
          idx: 5'd13,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_UID_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_DIGEST_BASE_ADDR) - 1
      },
      '{ //SIP_PUBK
          idx: 5'd12,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_DIGEST_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_UID_BASE_ADDR) - 1
      },
      '{ //CHIPLET_UID
          idx: 5'd11,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_DIGEST_BASE_ADDR) - 1
      },
      '{ //BL2_VERSION
          idx: 5'd10,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL2_VERSION_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR) - 1
      },
      '{ //BL1_VERSION
          idx: 5'd9,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL2_VERSION_BASE_ADDR) - 1
      },
      '{ //CHIPLET_PUBK_REVOKE
          idx: 5'd08,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR) - 1
      },
      '{ //CLASS_KEY
          idx: 5'd07,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR) - 1
      },
      '{ //RMA_CHIPLET_TOKEN
          idx: 5'd06,
          lock: {SECURE_TM_LOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR) - 1
      },
      '{ //RMA_SIP_TOKEN
          idx: 5'd05,
          lock: {SECURE_TM_LOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR) - 1
      },
      '{//SYS_DIS
          idx: 5'd04,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR) - 1
      },
      '{ //SIP_DIS
          idx: 5'd03,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR) - 1
      },
      '{ //transient rma enable
          idx: 5'd02,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_TRANSIENT_RMA_EN_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR) - 1
      },
      '{ //SBOOT_DIS
          idx: 5'd01,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_TRANSIENT_RMA_EN_BASE_ADDR) - 1
      },
      '{ //LC state
          idx: 5'd00,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR) - 1
      },
      '{ //lock bits
          idx: 5'h1f,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR),
          end_addr: efuse_offset(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR) - 1
      }
  };

endpackage
