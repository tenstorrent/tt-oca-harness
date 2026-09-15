// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Selftest environment package for the shared JTAG VIP wire harness.

`timescale 1ns / 1ps

package ocah_jtag_vip_env_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  import ocah_checker_uvm_pkg::*;
  import ocah_jtag_uvm_pkg::*;

  `include "ocah_jtag_vip_env.svh"
endpackage : ocah_jtag_vip_env_pkg
