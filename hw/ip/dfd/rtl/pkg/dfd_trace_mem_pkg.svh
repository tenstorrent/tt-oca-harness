// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef DFD_TRACE_MEM_PKG_SVH
`define DFD_TRACE_MEM_PKG_SVH

package dfd_trace_mem_pkg;

	// Struct Definition
	localparam TRC_SIZE_IN_KB = 16;
	localparam TRC_RAM_INDEX_WIDTH = $clog2(TRC_SIZE_IN_KB * 16);

	typedef struct packed {
		logic   mem_chip_en;
		logic   mem_wr_en;
		logic   [TRC_RAM_INDEX_WIDTH-1:0] mem_wr_addr;
		logic   mem_wr_mask_en;
		logic   [dfd_tn_pkg::TRC_RAM_DATA_WIDTH-1:0] mem_wr_data;
	} SinkMemPktIn_s;

	typedef struct packed {
		logic   [dfd_tn_pkg::TRC_RAM_DATA_WIDTH-1:0] mem_rd_data;
	} SinkMemPktOut_s;

endpackage

`endif
