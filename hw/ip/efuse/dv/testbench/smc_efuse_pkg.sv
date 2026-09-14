// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

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
  import smc_top_addrmap_pkg::*;

  function automatic longint unsigned efuse_offset(input longint unsigned addr);
    return addr - smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR;
  endfunction

  // Shadow register layout preserved from the legacy generated sub-block header.
  typedef struct packed {
    logic [37:0]   unused_lock_bits ;
    logic [0:0]   reserved_read_lock ;
    logic [0:0]   reserved_write_lock ;
    logic [0:0]   spi_config_read_lock ;
    logic [0:0]   spi_config_write_lock ;
    logic [0:0]   spi_ctrl_field_enable_read_lock ;
    logic [0:0]   spi_ctrl_field_enable_write_lock ;
    logic [0:0]   pll_and_sensor_read_lock ;
    logic [0:0]   pll_and_sensor_write_lock ;
    logic [0:0]   i3c_disable_read_lock ;
    logic [0:0]   i3c_disable_write_lock ;
    logic [0:0]   i2c_clock_gating_read_lock ;
    logic [0:0]   i2c_clock_gating_write_lock ;
    logic [0:0]   i2c_i3c_id_read_lock ;
    logic [0:0]   i2c_i3c_id_write_lock ;
    logic [0:0]   sop_topology_read_lock ;
    logic [0:0]   sop_topology_write_lock ;
    logic [0:0]   fabric_read_lock ;
    logic [0:0]   fabric_write_lock ;
    logic [0:0]   cluster_read_lock ;
    logic [0:0]   cluster_write_lock ;
    logic [0:0]   bira_dis_read_lock ;
    logic [0:0]   bira_dis_write_lock ;
    logic [0:0]   package_id_read_lock ;
    logic [0:0]   package_id_write_lock ;
    logic [0:0]   chiplet_id_read_lock ;
    logic [0:0]   chiplet_id_write_lock ;
  } smc_efuse_map_locks_reg_t;



  typedef struct packed {logic [255:0] chiplet_id_value;} smc_efuse_map_chiplet_id_reg_t;



  typedef struct packed {logic [255:0] package_id_value;} smc_efuse_map_package_id_reg_t;



  typedef struct packed {logic [16383:0] repair_data;} smc_efuse_map_bira_reg_t;



  typedef struct packed {logic [511:0] cluster_config;} smc_efuse_map_cluster_reg_t;



  typedef struct packed {logic [255:0] fabric_config;} smc_efuse_map_fabric_reg_t;



  typedef struct packed {logic [31:0] topology_serial;} smc_efuse_map_sop_topology_reg_t;



  typedef struct packed {logic [63:0] interface_id;} smc_efuse_map_i2c_i3c_id_reg_t;



  typedef struct packed {logic [31:0] clock_gating_config;} smc_efuse_map_i2c_clock_gating_reg_t;



  typedef struct packed {logic [31:0] disable_config;} smc_efuse_map_i3c_disable_reg_t;



  typedef struct packed {logic [4095:0] pll_sensor_config;} smc_efuse_map_pll_and_sensor_reg_t;



  typedef struct packed {logic [31:0] reserved_data;} smc_efuse_map_reserved_reg_t;



  typedef struct packed {
    smc_efuse_map_reserved_reg_t [64:0] reserved;
    smc_efuse_map_pll_and_sensor_reg_t pll_and_sensor;
    smc_efuse_map_i3c_disable_reg_t i3c_disable;
    smc_efuse_map_i2c_clock_gating_reg_t i2c_clock_gating;
    smc_efuse_map_i2c_i3c_id_reg_t [8:0] i2c_i3c_id;
    smc_efuse_map_sop_topology_reg_t sop_topology;
    smc_efuse_map_fabric_reg_t fabric;
    smc_efuse_map_cluster_reg_t cluster;
    smc_efuse_map_bira_reg_t bira;
    smc_efuse_map_package_id_reg_t package_id;
    smc_efuse_map_chiplet_id_reg_t chiplet_id;
    smc_efuse_map_locks_reg_t locks;
  } smc_efuse_map_regmap_t;
  `include "apb/typedef.svh"
  `include "axi/typedef.svh"
  `include "efuse_typedef.svh"

  // NumFuseWordWidth MAX is 32 bits

  // SMC efuse map is 3KB
  localparam int unsigned NumEfuseBits = 3 * (8 * 1024);  // 24576 bits
  localparam int unsigned NumFuseWordWidth = 32;

  localparam int unsigned NumFuseWords = NumEfuseBits / NumFuseWordWidth; // 768 words --- word == access granularity
  localparam int unsigned NumFuseBytes = NumFuseWords * 4;  // 3072 bytes

  localparam int unsigned NumFuseBitsWidth = $clog2(
      NumEfuseBits
  );  // 15 bits to encode 24576 bits <- used to create bit address type for bank
  localparam int unsigned NumFuseByteWidth = $clog2(
      NumFuseBytes
  );  // 12 bits to encode 3072 bytes <- used to create byte address type for bank
  localparam int unsigned NumFuseWordsWidth = $clog2(
      NumFuseWords
  );  // 10 bits to encode 768 words <- used to create counter type for bank - because we count by words
  localparam int unsigned SHADOW_REG_BITS = NumEfuseBits;

  typedef logic [NumFuseBitsWidth-1:0] efuse_addr_bit_t;
  typedef logic [NumFuseByteWidth-1:0] efuse_addr_byte_t;
  typedef logic [NumFuseWordWidth-1:0] efuse_data_t;
  typedef logic [NumFuseWordsWidth-1:0] efuse_word_counter_t;

  // Common interface types for efuse commands and responses
  `EFUSE_COMMAND_REQ_T(fuse_command_req_t, efuse_addr_bit_t, efuse_data_t, efuse_word_counter_t,
                       efuse_pkg::fuse_command_e)
  `EFUSE_COMMAND_RESP_T(fuse_command_resp_t, efuse_data_t)

  localparam int unsigned ADDR_WIDTH = 32;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;
  typedef logic [ADDR_WIDTH    -1:0] addr_t;
  typedef logic [DATA_WIDTH    -1:0] data_t;
  typedef logic [STRB_WIDTH    -1:0] strb_t;
  `AXI_LITE_TYPEDEF_ALL(efuse_axil, addr_t, data_t, strb_t)
  `APB_TYPEDEF_ALL(efuse_apb, addr_t, data_t, strb_t)


  // 15 real lockable fields (idx 0-14) + LOCKS meta-field (idx 6'h3F).
  //   LOCKS_META_IDX: fixed sentinel for the LOCKS meta-entry. Hardware never
  //                   applies lock bits to this entry. The idx is the max value
  //                   of efuse_pkg::rule_t.idx so it cannot collide with a real
  //                   field slot, regardless of how many fields are added later.
  localparam int unsigned NUM_EFUSE_FIELDS = 16;
  localparam logic [efuse_pkg::EFUSE_FIELD_MAP_IDX_WIDTH-1:0] LOCKS_META_IDX = '1;
  localparam logic [1:0] WRITE_UNLOCK = 2'b00;
  localparam logic [1:0] WRITE_SET_ONLY = 2'b10;
  localparam logic [1:0] WRITE_LOCK = 2'b11;
  localparam logic READ_UNLOCK = 1'b0;
  localparam logic READ_LOCK = 1'b1;

  // Physical OTP bits covered by LOCKS. SMC has no LOCKS_SPARE register, so the
  // lock field is the 64-bit LOCKS register occupying OTP words 0-1.
  localparam int unsigned LockFieldBits = $bits(smc_efuse_map_locks_reg_t);  // 64

  // efuse_lock_view_t presents the efuse_map_t union with the lock field at the
  // LSB end, mirroring where LOCKS sits in the packed struct.
  typedef struct packed {
    logic [NumEfuseBits-LockFieldBits-1:0] reserved;
    logic [LockFieldBits-1:0]              locks;
  } efuse_lock_view_t;

  typedef union packed {
    smc_efuse_map_regmap_t                         fields;
    efuse_lock_view_t                              locks;
    logic [NumFuseWords-1:0][NumFuseWordWidth-1:0] values;
  } efuse_map_t;

  // Lock field Description
  // lock[2:1] write: 00 -> unlock;11 -> lock ;10 -> set only;
  // lock[0]  read: 0 -> readable; 1 -> read locked

  localparam efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] EfuseFieldMap = '{
      '{
          idx: 6'd14,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(49)
          ),
          end_addr: smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SIZE - 1
      },
      '{
          idx: 6'd13,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(33)
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(49)
          ) - 1
      },
      '{
          idx: 6'd12,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(17)
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(33)
          ) - 1
      },
      '{
          idx: 6'd11,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(1)
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(17)
          ) - 1
      },
      '{
          idx: 6'd10,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(0)
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(1)
          ) - 1
      },
      '{
          idx: 6'd9,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_PLL_AND_SENSOR_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_RESERVED_BASE_ADDR(0)
          ) - 1
      },
      '{
          idx: 6'd8,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I3C_DISABLE_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_PLL_AND_SENSOR_BASE_ADDR
          ) - 1
      },
      '{
          idx: 6'd7,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_CLOCK_GATING_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I3C_DISABLE_BASE_ADDR
          ) - 1
      },
      '{
          idx: 6'd6,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0)
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_CLOCK_GATING_BASE_ADDR
          ) - 1
      },
      '{
          idx: 6'd5,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SOP_TOPOLOGY_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0)
          ) - 1
      },
      '{
          idx: 6'd4,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_FABRIC_BASE_ADDR),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SOP_TOPOLOGY_BASE_ADDR
          ) - 1
      },
      '{
          idx: 6'd3,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_CLUSTER_BASE_ADDR),
          end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_FABRIC_BASE_ADDR) - 1
      },
      '{
          idx: 6'd2,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BIRA_BASE_ADDR),
          end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_CLUSTER_BASE_ADDR) - 1
      },
      '{
          idx: 6'd1,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_PACKAGE_ID_BASE_ADDR
          ),
          end_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BIRA_BASE_ADDR) - 1
      },
      '{
          idx: 6'd0,
          lock: {WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_CHIPLET_ID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_PACKAGE_ID_BASE_ADDR
          ) - 1
      },
      '{
          idx: LOCKS_META_IDX,
          lock: {WRITE_SET_ONLY, READ_UNLOCK},
          start_addr: efuse_offset(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR),
          end_addr:
          efuse_offset
          (
              smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_CHIPLET_ID_BASE_ADDR
          ) - 1
      }
  };

endpackage
