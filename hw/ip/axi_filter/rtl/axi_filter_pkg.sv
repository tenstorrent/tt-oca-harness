// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold shared types and helpers for the AXI traffic filter.
//
// Defines filter hit and status typedefs and constants used by traffic_filter and the
// wrap.

package axi_filter_pkg;

  typedef struct packed {
    logic [3:0] write_filter_hit_debug;
    logic [3:0] read_filter_hit_debug;
  } filter_debug_t;

endpackage
