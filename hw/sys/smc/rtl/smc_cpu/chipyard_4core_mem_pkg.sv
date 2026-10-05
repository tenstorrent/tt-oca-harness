// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare memory-interface typedefs for the four-core Chipyard cluster.
//
// Declares ROM, scratch RAM, and L1 cache request/response structs, and the TileLink structs
// of the cluster boot ROM port.
// Bank-count localparams size the mem-swap and CPU wrapper port arrays.

`ifndef CHIPYARD_4CORE_MEMORY_INTERFACE
`define CHIPYARD_4CORE_MEMORY_INTERFACE

package chipyard_4core_mem_pkg;

  // Memory Parameters
  localparam int unsigned NumSramBanks = 32;
  localparam int unsigned NumIcacheTagBanks = 4;
  localparam int unsigned NumIcacheDataBanks = 8;
  localparam int unsigned NumDcacheTagBanks = 4;
  localparam int unsigned NumDcacheDataBanks = 4;

  // SRAM Size Parameters, 2^SramSize bytes
  localparam bit [5:0] SramSize = 20;

  localparam int unsigned Smc4coreScratchRamAddrWidth = 12;
  localparam int unsigned Smc4coreScratchRamDataWidth = 72;

  `include "chipyard_mem_defines.svh"

  // define all the structs needed for chipyard cpu memory interfaces
  `CHIPYARD_MEM_REQ_T(scratch_ram_req_t, Smc4coreScratchRamAddrWidth, Smc4coreScratchRamDataWidth,
                      1)
  `CHIPYARD_MEM_RSP_T(scratch_ram_rsp_t, Smc4coreScratchRamDataWidth)

  `CHIPYARD_MEM_REQ_T(l1_icache_tag_req_t, 5, 94, 2)
  `CHIPYARD_MEM_RSP_T(l1_icache_tag_rsp_t, 94)

  `CHIPYARD_MEM_REQ_T(l1_icache_data_req_t, 8, 66, 2)
  `CHIPYARD_MEM_RSP_T(l1_icache_data_rsp_t, 66)

  `CHIPYARD_MEM_REQ_T(l1_dcache_tag_req_t, 5, 108, 2)
  `CHIPYARD_MEM_RSP_T(l1_dcache_tag_rsp_t, 108)

  `CHIPYARD_MEM_REQ_T(l1_dcache_data_req_t, 8, 144, 2)
  `CHIPYARD_MEM_RSP_T(l1_dcache_data_rsp_t, 144)

  `CHIPYARD_MEM_REQ_T(rom_req_t, 14, 64, 1)
  `CHIPYARD_MEM_RSP_T(rom_rsp_t, 64)

  // Chipyard tilelink interface that gets converted to a generic memory interface
  `CHIPYARD_ROM_REQ_T(rom_tilelink_req_t, 32, 15)
  `CHIPYARD_ROM_RSP_T(rom_tilelink_rsp_t, 64, 15)

endpackage : chipyard_4core_mem_pkg

`endif
