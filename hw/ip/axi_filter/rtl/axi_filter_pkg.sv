// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold shared types and helpers for the AXI traffic filter.
//
// Defines filter_debug_t, which packs 4-bit write-path and read-path filter hit indices; no
// module in the open tree references it.

package axi_filter_pkg;

  typedef struct packed {
    logic [3:0] write_filter_hit_debug;
    logic [3:0] read_filter_hit_debug;
  } filter_debug_t;

endpackage
