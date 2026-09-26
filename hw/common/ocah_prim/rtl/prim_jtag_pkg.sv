// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Declare shared JTAG TAP and scan-control struct types for the prim_jtag_* cells.
//
// jtag_tap_ctrl_t carries TMS, TRST_n, and TCK for the TAP.
// jtag_scan_ctrl_t bundles TCK, select, capture/shift/update enables, resets, runbist, and
// the Test-Logic-Reset and Run-Test/Idle state flags.

package prim_jtag_pkg;

  // JTAG TAP control interface
  typedef struct packed {
    logic tms;
    logic trst_n;
    logic tck;
  } jtag_tap_ctrl_t;

  // JTAG scan control interface
  typedef struct packed {
    logic runbist;
    logic test_logic_reset;
    logic run_test_idle;
    logic update_en;
    logic shift_en;
    logic capture_en;
    logic select;
    logic chrst_n;
    logic rst_n;
    logic tck;
  } jtag_scan_ctrl_t;

endpackage
