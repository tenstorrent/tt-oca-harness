// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
`ifndef TRACE_MEM_PKG_SVH
`define TRACE_MEM_PKG_SVH

package trace_mem_pkg;

  // Sink RAM depth these structs are sized for. trace_wrapper elaboration-checks
  // its TRC_RAM_INDEX parameter against this; the two must agree for the packet
  // structs to be usable on a port.
  localparam TRC_RAM_INDEX       = 256;
  localparam TRC_RAM_INDEX_WIDTH = $clog2(TRC_RAM_INDEX);

  typedef struct packed {
    logic                                  mem_chip_en;
    logic                                  mem_wr_en;
    logic [TRC_RAM_INDEX_WIDTH-1:0]        mem_wr_addr;
    logic                                  mem_wr_mask_en;
    logic [tn_pkg::TRC_RAM_DATA_WIDTH-1:0] mem_wr_data;
  } SinkMemPktIn_s;

  typedef struct packed {
    logic [tn_pkg::TRC_RAM_DATA_WIDTH-1:0] mem_rd_data;
  } SinkMemPktOut_s;

endpackage

`endif
