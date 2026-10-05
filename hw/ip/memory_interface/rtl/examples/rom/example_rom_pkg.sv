// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold example ROM parameters for memory_interface bring-up.
//
// Supplies the 32-bit address, 64-bit data and 1-bit ID and user widths, the mem_req_t and
// mem_rsp_t memory-port structs, and the AXI4, AXI4-Lite and APB4 typedefs used by the ROM
// example binding.

package example_rom_pkg;

  `include "axi/typedef.svh"
  `include "apb/typedef.svh"

  ///////////////////////////////
  // User Specified Parameters //
  ///////////////////////////////
  localparam int unsigned MemAddrWidth = 32;
  localparam int unsigned MemDataWidth = 64;  // 64-bit to match SEP AXI bus.
  localparam int unsigned MemIdWidth = 1;

  localparam int unsigned AxiUserWidth = 1;

  //////////////////////
  // Memory interface //
  //////////////////////
  typedef logic [MemAddrWidth-1:0] mem_addr_t;
  typedef logic [MemDataWidth-1:0] mem_data_t;
  typedef logic [MemDataWidth/8-1:0] mem_strb_t;

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
  localparam int unsigned AxiStrbWidth = MemDataWidth / 8;

  typedef logic [MemAddrWidth-1:0] rom_axi_addr_t;
  typedef logic [MemDataWidth-1:0] rom_axi_data_t;
  typedef logic [MemIdWidth-1:0] rom_axi_id_t;
  typedef logic [AxiStrbWidth-1:0] rom_axi_strb_t;
  typedef logic [AxiUserWidth-1:0] rom_axi_user_t;

  `AXI_TYPEDEF_ALL(rom_axi, rom_axi_addr_t, rom_axi_id_t, rom_axi_data_t, rom_axi_strb_t,
                   rom_axi_user_t)

  /////////////////////////
  // AXI4-Lite interface //
  /////////////////////////
  localparam int unsigned AxiLiteStrbWidth = MemDataWidth / 8;

  typedef logic [MemAddrWidth-1:0] rom_axil_addr_t;
  typedef logic [MemDataWidth-1:0] rom_axil_data_t;
  typedef logic [AxiLiteStrbWidth-1:0] rom_axil_strb_t;

  `AXI_LITE_TYPEDEF_ALL(rom_axil, rom_axil_addr_t, rom_axil_data_t, rom_axil_strb_t)

  ////////////////////
  // APB4 interface //
  ////////////////////
  localparam int unsigned ApbAddrWidth = MemAddrWidth;
  localparam int unsigned ApbDataWidth = MemDataWidth;
  localparam int unsigned ApbStrbWidth = MemDataWidth / 8;

  typedef logic [MemAddrWidth-1:0] rom_apb_addr_t;
  typedef logic [MemDataWidth-1:0] rom_apb_data_t;
  typedef logic [ApbStrbWidth-1:0] rom_apb_strb_t;

  `APB_TYPEDEF_ALL(rom_apb, rom_apb_addr_t, rom_apb_data_t, rom_apb_strb_t)
endpackage
