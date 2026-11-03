// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Adopter fuse region of the OSS reference tops, sized from the example map in
// hw/ip/efuse/doc/smc_adopter_fuse_map.rdl: 16 MEM_REPAIR, 8 SENSOR_TRIM and 8 ADOPTER_SPARE
// registers of 128 bits. Each register array is one lock region, so ADOPTER_LOCKS pairs 0-2
// are used. The window base depends on the eFuse shim size, so each wrapper sets it.

package smc_adopter_fuse_example_pkg;

  localparam int unsigned FuseWords = 128;  // 32 registers of four 32-bit words, 512 bytes.

  localparam smc_efuse_pkg::adopter_lock_region_end_t LockRegionEnd = '{
      0: 16'd64,   // MEM_REPAIR[16]
      1: 16'd96,   // SENSOR_TRIM[8]
      2: 16'd128,  // ADOPTER_SPARE[8]
      default: 16'd0
  };

endpackage
