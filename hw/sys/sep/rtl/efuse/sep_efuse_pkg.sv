// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

package sep_efuse_pkg;
  `include "sep_efuse_map_reg.svh"
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
        start_addr: RESERVED_LAST_256_REG_OFFSET,
        end_addr: SEP_EFUSE_MAP_REG_MAP_SIZE - 1
    },
    '{ // RESERVED_7
        idx: 5'd28,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_7_REG_OFFSET,
        end_addr: RESERVED_LAST_256_REG_OFFSET - 1
    },
    '{ // RESERVED_6
        idx: 5'd27,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_6_REG_OFFSET,
        end_addr: RESERVED_7_REG_OFFSET - 1
    },
    '{ // RESERVED_5
        idx: 5'd26,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_5_REG_OFFSET,
        end_addr: RESERVED_6_REG_OFFSET - 1
    },
    '{ // RESERVED_4
        idx: 5'd25,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_4_REG_OFFSET,
        end_addr: RESERVED_5_REG_OFFSET - 1
    },
    '{ // RESERVED_3
        idx: 5'd24,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_3_REG_OFFSET,
        end_addr: RESERVED_4_REG_OFFSET - 1
    },
    '{ // RESERVED_2
        idx: 5'd23,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_2_REG_OFFSET,
        end_addr: RESERVED_3_REG_OFFSET - 1
    },
    '{ // RESERVED_1
        idx: 5'd22,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_1_REG_OFFSET,
        end_addr: RESERVED_2_REG_OFFSET - 1
    },
    '{ // RESERVED_0
        idx: 5'd21,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: RESERVED_0_REG_OFFSET,
        end_addr: RESERVED_1_REG_OFFSET - 1
    },
    '{ // PUBK_HASH_1
        idx: 5'd20,
        lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
        start_addr: PUBLIC_KEY_1_REG_OFFSET,
        end_addr: RESERVED_0_REG_OFFSET - 1
    },
       '{ // PUBK_HASH_0
           idx: 5'd19,
           lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
           start_addr: PUBLIC_KEY_0_REG_OFFSET,
           end_addr: PUBLIC_KEY_1_REG_OFFSET - 1
       },
      '{ // sep_spi_ctrl
          idx: 5'd18,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SEP_SPI_CTRL_FIELD_EN_REG_OFFSET,
          end_addr: PUBLIC_KEY_0_REG_OFFSET - 1
      },
      '{ // SEP_ROM_CTRL
          idx: 5'd17,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SEP_ROM_CTRL_REG_OFFSET,
          end_addr: SEP_SPI_CTRL_FIELD_EN_REG_OFFSET - 1
      },
      '{ //STATUS_RPT
          idx: 5'd16,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: STATUS_RPT_REG_OFFSET,
          end_addr: SEP_ROM_CTRL_REG_OFFSET - 1
      },
      '{ //SYS_UID
          idx: 5'd15,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SYS_UID_REG_OFFSET,
          end_addr: STATUS_RPT_REG_OFFSET - 1
      },
      '{ //SYS_PUBK
          idx: 5'd14,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SYS_PUBK_DIGEST_REG_OFFSET,
          end_addr: SYS_UID_REG_OFFSET - 1
      },
      '{ //SIP_UID
          idx: 5'd13,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SIP_UID_REG_OFFSET,
          end_addr: SYS_PUBK_DIGEST_REG_OFFSET - 1
      },
      '{ //SIP_PUBK
          idx: 5'd12,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SIP_PUBK_DIGEST_REG_OFFSET,
          end_addr: SIP_UID_REG_OFFSET - 1
      },
      '{ //CHIPLET_UID
          idx: 5'd11,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: CHIPLET_UID_REG_OFFSET,
          end_addr: SIP_PUBK_DIGEST_REG_OFFSET - 1
      },
      '{ //BL2_VERSION
          idx: 5'd10,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: BL2_VERSION_REG_OFFSET,
          end_addr: CHIPLET_UID_REG_OFFSET - 1
      },
      '{ //BL1_VERSION
          idx: 5'd9,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: BL1_VERSION_REG_OFFSET,
          end_addr: BL2_VERSION_REG_OFFSET - 1
      },
      '{ //CHIPLET_PUBK_REVOKE
          idx: 5'd08,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: CHIPLET_PUBK_REVOKE_REG_OFFSET,
          end_addr: BL1_VERSION_REG_OFFSET - 1
      },
      '{ //CLASS_KEY
          idx: 5'd07,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: CLASS_KEY_REG_OFFSET,
          end_addr: CHIPLET_PUBK_REVOKE_REG_OFFSET - 1
      },
      '{ //RMA_CHIPLET_TOKEN
          idx: 5'd06,
          lock: {SECURE_TM_LOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: RMA_CHIPLET_TOKEN_DIGEST_REG_OFFSET,
          end_addr: CLASS_KEY_REG_OFFSET - 1
      },
      '{ //RMA_SIP_TOKEN
          idx: 5'd05,
          lock: {SECURE_TM_LOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: RMA_SIP_TOKEN_DIGEST_REG_OFFSET,
          end_addr: RMA_CHIPLET_TOKEN_DIGEST_REG_OFFSET - 1
      },
      '{//SYS_DIS
          idx: 5'd04,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: SYS_DIS_REG_OFFSET,
          end_addr: RMA_SIP_TOKEN_DIGEST_REG_OFFSET - 1
      },
      '{ //SIP_DIS
          idx: 5'd03,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: SIP_DIS_REG_OFFSET,
          end_addr: SYS_DIS_REG_OFFSET - 1
      },
      '{ //transient rma enable
          idx: 5'd02,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: TRANSIENT_RMA_EN_REG_OFFSET,
          end_addr: SIP_DIS_REG_OFFSET - 1
      },
      '{ //SBOOT_DIS
          idx: 5'd01,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr: SBOOT_DIS_REG_OFFSET,
          end_addr: TRANSIENT_RMA_EN_REG_OFFSET - 1
      },
      '{ //LC state
          idx: 5'd00,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: LC_STATE_REG_OFFSET,
          end_addr: SBOOT_DIS_REG_OFFSET - 1
      },
      '{ //lock bits
          idx: 5'h1f,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: LOCKS_REG_OFFSET,
          end_addr: LC_STATE_REG_OFFSET - 1
      }
  };

endpackage
