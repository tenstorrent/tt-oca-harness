// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequences of the shared JTAG VIP wire-harness selftests, the
// SV-UVM twins of dv/cocotb/tests.

`timescale 1ns / 1ps

package ocah_jtag_vip_seq_lib_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  import ocah_lib_pkg::*;
  import ocah_checker_uvm_pkg::*;
  import ocah_jtag_uvm_pkg::*;

  `include "ocah_jtag_vip_base_test_seq.svh"
  `include "ocah_jtag_idcode_test_seq.svh"
  `include "ocah_jtag_bypass_test_seq.svh"
  `include "ocah_jtag_register_test_seq.svh"
  `include "ocah_jtag_tap_reset_test_seq.svh"
endpackage : ocah_jtag_vip_seq_lib_pkg
