// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

/*************************************************************************
*
* SMC Efuse Package
*
*
* All rights reserved.
*
* Redistribution and use in source and binary forms, with or without
 */

package smc_efuse_pkg;
  `include "smc_efuse_map_reg.svh"
  `include "efuse_typedef.svh"

  // NumFuseWordWidth MAX is 32 bits

  // SMC efuse map is 3KB
  localparam int unsigned NumEfuseBits = 3 * (8 * 1024);                  // 24576 bits
  localparam int unsigned NumFuseWordWidth = 32;

  localparam int unsigned NumFuseWords = NumEfuseBits / NumFuseWordWidth; // 768 words --- word == access granularity
  localparam int unsigned NumFuseBytes = NumFuseWords * 4;                // 3072 bytes

  localparam int unsigned NumFuseBitsWidth = $clog2(NumEfuseBits);      // 15 bits to encode 24576 bits <- used to create bit address type for bank
  localparam int unsigned NumFuseByteWidth = $clog2(NumFuseBytes);      // 12 bits to encode 3072 bytes <- used to create byte address type for bank
  localparam int unsigned NumFuseWordsWidth = $clog2(NumFuseWords);     // 10 bits to encode 768 words <- used to create counter type for bank - because we count by words
  localparam int unsigned SHADOW_REG_BITS = NumEfuseBits;

  typedef logic [NumFuseBitsWidth-1:0]  efuse_addr_bit_t;
  typedef logic [NumFuseByteWidth-1:0]  efuse_addr_byte_t;
  typedef logic [NumFuseWordWidth-1:0]  efuse_data_t;
  typedef logic [NumFuseWordsWidth-1:0] efuse_word_counter_t;

  // Common interface types for efuse commands and responses
  `EFUSE_COMMAND_REQ_T(fuse_command_req_t, efuse_addr_bit_t, efuse_data_t, efuse_word_counter_t, efuse_pkg::fuse_command_e)
  `EFUSE_COMMAND_RESP_T(fuse_command_resp_t, efuse_data_t)

  localparam int unsigned NUM_EFUSE_FIELDS = 16;
  localparam logic [1:0] WRITE_UNLOCK = 2'b00;
  localparam logic [1:0] WRITE_SET_ONLY = 2'b10;
  localparam logic [1:0] WRITE_LOCK = 2'b11;
  localparam logic READ_UNLOCK = 1'b0;
  localparam logic READ_LOCK = 1'b1;

  typedef union packed {
    smc_efuse_map_regmap_t f;
    logic [NumFuseWords-1:0][NumFuseWordWidth-1:0] values;
  } efuse_map_t;

  // Lock field Description
  // lock[2:1] write: 00 -> unlock;11 -> lock ;10 -> set only;
  // lock[0]  read: 0 -> readable; 1 -> read locked

  localparam efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] EfuseFieldMap = '{
       '{idx: 5'd14,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: RESERVED_49__REG_OFFSET,
         end_addr: SMC_EFUSE_MAP_REG_MAP_SIZE-1
       },
       '{idx: 5'd13,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: RESERVED_33__REG_OFFSET,
         end_addr: RESERVED_49__REG_OFFSET-1
       },
       '{idx: 5'd12,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: RESERVED_17__REG_OFFSET,
         end_addr: RESERVED_33__REG_OFFSET-1
       },
       '{idx: 5'd11,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: RESERVED_1__REG_OFFSET,
         end_addr: RESERVED_17__REG_OFFSET-1
       },
       '{idx: 5'd10,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: RESERVED_0__REG_OFFSET,
         end_addr: RESERVED_1__REG_OFFSET-1
       },
      '{idx: 5'd9,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: PLL_AND_SENSOR_REG_OFFSET,
        end_addr: RESERVED_0__REG_OFFSET-1
       },
      '{idx: 5'd8,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: I3C_DISABLE_REG_OFFSET,
        end_addr: PLL_AND_SENSOR_REG_OFFSET-1
       },
      '{idx: 5'd7,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: I2C_CLOCK_GATING_REG_OFFSET,
        end_addr: I3C_DISABLE_REG_OFFSET-1
       },
       '{idx: 5'd6,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: I2C_I3C_ID_0__REG_OFFSET,
         end_addr: I2C_CLOCK_GATING_REG_OFFSET-1
        },
      '{idx: 5'd5,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: SOP_TOPOLOGY_REG_OFFSET,
        end_addr: I2C_I3C_ID_0__REG_OFFSET-1
       },
      '{idx: 5'd4,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: FABRIC_REG_OFFSET,
        end_addr: SOP_TOPOLOGY_REG_OFFSET-1
       },
      '{idx: 5'd3,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: CLUSTER_REG_OFFSET,
        end_addr: FABRIC_REG_OFFSET-1
       },
      '{idx: 5'd2,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: BIRA_REG_OFFSET,
        end_addr: CLUSTER_REG_OFFSET-1
       },
       '{idx: 5'd1,
         lock: {WRITE_UNLOCK, READ_UNLOCK},
         start_addr: PACKAGE_ID_REG_OFFSET,
         end_addr: BIRA_REG_OFFSET-1
        },
      '{idx: 5'd0,
        lock: {WRITE_UNLOCK, READ_UNLOCK},
        start_addr: CHIPLET_ID_REG_OFFSET,
        end_addr: PACKAGE_ID_REG_OFFSET-1
       },
      '{
          idx: 5'h1f,
          lock: {WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: LOCKS_REG_OFFSET,
          end_addr: CHIPLET_ID_REG_OFFSET-1
      }
  };

  // Reserved Section
  localparam int unsigned ROM_CTRL_REG_INDEX = 0;
  localparam int unsigned ROM_FLIP_ENDIANNESS_START_BIT = 0;
  localparam int unsigned SRAM_DISABLE_AUTO_INIT_START_BIT = 6;

endpackage
