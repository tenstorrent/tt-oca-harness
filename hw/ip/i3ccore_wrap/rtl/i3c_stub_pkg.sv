// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Minimal package contracts used while i3c-core is stubbed out of the open build.
// Keep these typedef widths aligned with the wrapper stub port comments.
package I3CCSR_pkg;

  // i3ccore_stub implements neither controller nor target mode (it terminates
  // the AXI-Lite interface with a DECERR/SLVERR slave and ties off every other
  // output, including the DAT/DCT memory ports) -- so both stay 0 until the
  // real open-source controller replaces the stub. Consumers gated on these
  // (e.g. smc_ip_integration.sv's DAT/DCT memory instantiation) correctly skip
  // instantiating hardware the stub can't drive anyway.
  localparam bit CONTROLLER_SUPPORT = 1'b0;
  localparam bit TARGET_SUPPORT = 1'b0;

  localparam int unsigned I3CCSR_MIN_ADDR_WIDTH = 11;
  localparam int unsigned I3CCSR_DATA_WIDTH = 32;

  localparam dat_depth = 'hf;
  localparam dct_depth = 'hf;

  localparam int unsigned resp_fifo_size = 8;
  localparam int unsigned cmd_fifo_size = 8;
  localparam int unsigned rx_fifo_size = 8;
  localparam int unsigned tx_fifo_size = 8;
  localparam int unsigned ibi_fifo_size = 8;

  localparam int unsigned tti_rx_desc_fifo_size = 8;
  localparam int unsigned tti_tx_desc_fifo_size = 8;
  localparam int unsigned tti_rx_fifo_size = 8;
  localparam int unsigned tti_tx_fifo_size = 8;
  localparam int unsigned tti_ibi_fifo_size = 8;

endpackage

package i3c_pkg;

  localparam int unsigned DatAw = 4;
  localparam int unsigned DctAw = 4;

  typedef struct packed {
    logic [63:0] rdata;
    logic        rvalid;
    logic [1:0]  rerror;
  } dat_mem_src_t;

  typedef struct packed {
    logic          req;
    logic          write;
    logic [DatAw-1:0] addr;
    logic [63:0]   wdata;
    logic [63:0]   wmask;
  } dat_mem_sink_t;

  typedef struct packed {
    logic [127:0] rdata;
    logic         rvalid;
    logic [1:0]   rerror;
  } dct_mem_src_t;

  typedef struct packed {
    logic          req;
    logic          write;
    logic [DctAw-1:0] addr;
    logic [127:0]  wdata;
    logic [127:0]  wmask;
  } dct_mem_sink_t;

endpackage
