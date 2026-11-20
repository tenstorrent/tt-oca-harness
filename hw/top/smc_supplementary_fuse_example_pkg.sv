// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Supplementary fuse region of the OSS reference tops, sized from the example map in
// hw/top/smc_supplementary_fuse_map.rdl: 16 MEM_REPAIR, 8 SENSOR_TRIM and 8 SUPPLEMENTARY_SPARE
// registers of 128 bits. Each register array is one lock region, so SUPPLEMENTARY_LOCKS pairs 0-2
// are used.

package smc_supplementary_fuse_example_pkg;

  localparam int unsigned Base = int'(  // Window at the base of the supplementary fuse slot.
      smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_FUSE_BASE_ADDR -
      smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_BASE_ADDR);

  localparam int unsigned FuseWords = 128;  // 32 registers of four 32-bit words, 512 bytes.

  localparam smc_efuse_pkg::supplementary_lock_region_end_t LockRegionEnd = '{
      0: 16'd64,   // MEM_REPAIR[16]
      1: 16'd96,   // SENSOR_TRIM[8]
      2: 16'd128,  // SUPPLEMENTARY_SPARE[8]
      default: 16'd0
  };

endpackage
