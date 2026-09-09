// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared-AXI-VIP selftest environment package (`<DUT>_env_pkg` convention).
// The environment wires the VIP's own master env, fault-slave agent, and
// passive observation env onto the harness ocah_axi_if, and a second master
// env, slave agent, and passive env around the struct-port bridge — the SV-UVM
// twin of the cocotb bundles in dv/cocotb/ocah_axi_vip_harness.py.

`timescale 1ns / 1ps

package ocah_axi_vip_env_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import ocah_axi_uvm_pkg::*;

  `include "ocah_axi_vip_env.svh"

endpackage : ocah_axi_vip_env_pkg
