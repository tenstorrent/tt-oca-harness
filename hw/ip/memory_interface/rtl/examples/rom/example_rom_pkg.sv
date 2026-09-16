// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------
// Example ROM Package
//
//------------------------------------------------


package example_rom_pkg;

  `include "axi/typedef.svh"
  `include "apb/typedef.svh"

  ///////////////////////////////
  // User Specified Parameters //
  ///////////////////////////////
  localparam int unsigned MEM_ADDR_WIDTH = 32;
  localparam int unsigned MEM_DATA_WIDTH = 64;  // 64-bit to match SEP AXI bus
  localparam int unsigned MEM_ID_WIDTH = 1;

  localparam int unsigned AXI_USER_WIDTH = 1;

  //////////////////////
  // Memory interface //
  //////////////////////
  typedef logic [MEM_ADDR_WIDTH-1:0] mem_addr_t;
  typedef logic [MEM_DATA_WIDTH-1:0] mem_data_t;
  typedef logic [MEM_DATA_WIDTH/8-1:0] mem_strb_t;

  typedef struct packed {
    logic           req;
    mem_addr_t      addr;
    mem_data_t      wdata;
    mem_strb_t      strb;
    axi_pkg::atop_t atop;
    logic           wenable;
  } mem_req_t;

  typedef struct packed {
    logic           gnt;
    logic           rvalid;
    mem_data_t      rdata;
  } mem_rsp_t;

  ////////////////////
  // AXI4 interface //
  ////////////////////
  localparam int unsigned AXI_STRB_WIDTH = MEM_DATA_WIDTH / 8;

  typedef logic [MEM_ADDR_WIDTH-1:0] rom_axi_addr_t;
  typedef logic [MEM_DATA_WIDTH-1:0] rom_axi_data_t;
  typedef logic [MEM_ID_WIDTH-1:0] rom_axi_id_t;
  typedef logic [AXI_STRB_WIDTH-1:0] rom_axi_strb_t;
  typedef logic [AXI_USER_WIDTH-1:0] rom_axi_user_t;

  `AXI_TYPEDEF_ALL(rom_axi, rom_axi_addr_t, rom_axi_id_t, rom_axi_data_t, rom_axi_strb_t,
                   rom_axi_user_t)

  /////////////////////////
  // AXI4-Lite interface //
  /////////////////////////
  localparam int unsigned AXI_LITE_STRB_WIDTH = MEM_DATA_WIDTH / 8;

  typedef logic [MEM_ADDR_WIDTH-1:0] rom_axil_addr_t;
  typedef logic [MEM_DATA_WIDTH-1:0] rom_axil_data_t;
  typedef logic [AXI_LITE_STRB_WIDTH-1:0] rom_axil_strb_t;

  `AXI_LITE_TYPEDEF_ALL(rom_axil, rom_axil_addr_t, rom_axil_data_t, rom_axil_strb_t)

  ////////////////////
  // APB4 interface //
  ////////////////////
  localparam int unsigned APB_ADDR_WIDTH = MEM_ADDR_WIDTH;
  localparam int unsigned APB_DATA_WIDTH = MEM_DATA_WIDTH;
  localparam int unsigned APB_STRB_WIDTH = MEM_DATA_WIDTH / 8;

  typedef logic [MEM_ADDR_WIDTH-1:0] rom_apb_addr_t;
  typedef logic [MEM_DATA_WIDTH-1:0] rom_apb_data_t;
  typedef logic [APB_STRB_WIDTH-1:0] rom_apb_strb_t;

  `APB_TYPEDEF_ALL(rom_apb, rom_apb_addr_t, rom_apb_data_t, rom_apb_strb_t)
endpackage
