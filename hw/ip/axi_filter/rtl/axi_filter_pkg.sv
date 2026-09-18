// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AXI Filter Package
//
//-----------------------------------------------------------------------------

package axi_filter_pkg;

  typedef struct packed {
    logic [3:0] write_filter_hit_debug;
    logic [3:0] read_filter_hit_debug;
  } filter_debug_t;

endpackage
