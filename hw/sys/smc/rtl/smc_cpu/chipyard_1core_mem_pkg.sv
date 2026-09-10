// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef CHIPYARD_1CORE_MEMORY_INTERFACE
`define CHIPYARD_1CORE_MEMORY_INTERFACE

package chipyard_1core_mem_pkg;

  localparam int unsigned SMC_1CORE_SCRATCH_RAM_ADDR_WIDTH = 11;
  localparam int unsigned SMC_1CORE_SCRATCH_RAM_DATA_WIDTH = 72;

  // Memory Parameters
  localparam int unsigned NUM_SRAM_BANKS = 4;
  // define the following at minimum widths
  localparam int unsigned NUM_ICACHE_TAG_BANKS = 1;
  localparam int unsigned NUM_ICACHE_DATA_BANKS = 1;
  localparam int unsigned NUM_DCACHE_TAG_BANKS = 1;
  localparam int unsigned NUM_DCACHE_DATA_BANKS = 1;

  // SRAM Size Parameters, 2^SRAM_SIZE bytes
  localparam bit [5:0] SRAM_SIZE = 16;

  `include "chipyard_mem_defines.svh"

  // define all the structs needed for chipyard cpu memory interfaces
  `CHIPYARD_MEM_REQ_T(scratch_ram_req_t, SMC_1CORE_SCRATCH_RAM_ADDR_WIDTH,
                      SMC_1CORE_SCRATCH_RAM_DATA_WIDTH, 1)
  `CHIPYARD_MEM_RSP_T(scratch_ram_rsp_t, SMC_1CORE_SCRATCH_RAM_DATA_WIDTH)

  // define the following at minimum widths
  `CHIPYARD_MEM_REQ_T(l1_icache_tag_req_t, 1, 1, 1)
  `CHIPYARD_MEM_RSP_T(l1_icache_tag_rsp_t, 1)

  `CHIPYARD_MEM_REQ_T(l1_icache_data_req_t, 1, 1, 1)
  `CHIPYARD_MEM_RSP_T(l1_icache_data_rsp_t, 1)

  `CHIPYARD_MEM_REQ_T(l1_dcache_tag_req_t, 1, 1, 1)
  `CHIPYARD_MEM_RSP_T(l1_dcache_tag_rsp_t, 1)

  `CHIPYARD_MEM_REQ_T(l1_dcache_data_req_t, 1, 1, 1)
  `CHIPYARD_MEM_RSP_T(l1_dcache_data_rsp_t, 1)

  `CHIPYARD_ROM_REQ_T(rom_req_t, 1, 1)
  `CHIPYARD_ROM_RSP_T(rom_rsp_t, 1, 1)

endpackage : chipyard_1core_mem_pkg

`endif
