// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Test classes of the shared JTAG VIP wire-harness selftests, included by
// dv/tb/tb_top.sv in its SV-UVM shape.

`include "uvm_macros.svh"
import ocah_lib_pkg::*;
import ocah_jtag_vip_env_pkg::*;
import ocah_jtag_vip_seq_lib_pkg::*;

`include "ocah_jtag_vip_base_test.svh"
`include "ocah_jtag_idcode_test.svh"
`include "ocah_jtag_bypass_test.svh"
`include "ocah_jtag_register_test.svh"
`include "ocah_jtag_tap_reset_test.svh"
