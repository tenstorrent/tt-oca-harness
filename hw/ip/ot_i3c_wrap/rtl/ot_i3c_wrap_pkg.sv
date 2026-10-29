// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold the register interface constants and external memory port types of the
// multi-instance OpenTitan I3C wrapper.
//
// Each memory sink carries the clock of the instance that drives it. Read data
// is expected on the source one cycle after a read request.

package ot_i3c_wrap_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////////////
  // Register Interface Definitions //
  ////////////////////////////////////

  localparam int unsigned RegAddrWidth = 32;
  localparam int unsigned RegDataWidth = 32;
  localparam int unsigned RegStrbWidth = RegDataWidth / 8;

  typedef logic [RegAddrWidth-1:0] reg_addr_t;
  typedef logic [RegDataWidth-1:0] reg_data_t;
  typedef logic [RegStrbWidth-1:0] reg_strb_t;

  `AXI_LITE_TYPEDEF_ALL(axil, reg_addr_t, reg_data_t, reg_strb_t)

  localparam int unsigned I3cInstanceSpacing = 32'h1000;  // Address spacing between instances.
  localparam int unsigned I3cRegAddrWidth = 12;  // Register address width per instance.

  //////////////////////////
  // External Memory Ports //
  //////////////////////////

  localparam int unsigned BufAw = i3c_pkg::BufAddrW;
  localparam int unsigned BufDw = 32;
  localparam int unsigned DatAw = $clog2(i3c_pkg::NumDATEntries);
  localparam int unsigned DatDw = $bits(i3c_pkg::i3c_dat_mem_t);
  localparam int unsigned DctAw = $clog2(i3c_pkg::NumDCTEntries);
  localparam int unsigned DctDw = $bits(i3c_pkg::i3c_dct_mem_t);

  // Message buffer.
  typedef struct packed {
    logic             clk;
    logic             req;
    logic             write;
    logic [BufAw-1:0] addr;
    logic [BufDw-1:0] wdata;
    logic [BufDw-1:0] wmask;
  } buf_mem_sink_t;

  typedef struct packed {logic [BufDw-1:0] rdata;} buf_mem_src_t;

  // Device Address Table.
  typedef struct packed {
    logic             clk;
    logic             req;
    logic             write;
    logic [DatAw-1:0] addr;
    logic [DatDw-1:0] wdata;
    logic [DatDw-1:0] wmask;
  } dat_mem_sink_t;

  typedef struct packed {logic [DatDw-1:0] rdata;} dat_mem_src_t;

  // Device Characteristics Table.
  typedef struct packed {
    logic             clk;
    logic             req;
    logic             write;
    logic [DctAw-1:0] addr;
    logic [DctDw-1:0] wdata;
    logic [DctDw-1:0] wmask;
  } dct_mem_sink_t;

  typedef struct packed {logic [DctDw-1:0] rdata;} dct_mem_src_t;

endpackage
