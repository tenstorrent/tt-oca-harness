// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Generic pin-level IEEE 1149.1 JTAG interface, shared across OCAH DUTs
// (DTP and SMU expose these exact raw TAP pins at their TB tops).
//
// Scope: JTAG pins ONLY. DUT-specific TB collateral (system resets, decoded
// TAP-state observables, ...) belongs in a DUT-local interface next to that
// DUT's tb_top, never here.
//
// This is the SystemVerilog side of ocah_jtag_vip; the cocotb BFM lives in
// the sibling cocotb/ modules and the SV-UVM agent in uvm/.

interface ocah_jtag_if;

  // Driven by the TB (BFM / sequence / agent driver).
  logic tck;
  logic tms;
  logic trst_n;   // active-low asynchronous TAP reset
  logic tdi;

  // Driven by the DUT.
  logic tdo;
  logic tdo_oen;

`ifdef OCAH_JTAG_VENDOR_IF
  // Commercial-VIP nesting hook (see README "Template Contract"). An
  // adopter overlay (run_dv --overlay) supplies `ocah_jtag_vendor_if.svh`
  // on an overlay incdir together with the OCAH_JTAG_VENDOR_IF define; the
  // OSS tree ships no copy of that file. It nests the vendor VIP's own SV
  // interface HERE, wired from this interface's boundary signals, so DUT
  // tb_tops never instantiate vendor collateral directly, e.g.:
  //   <vendor>_jtag_if u_vendor_if (...);
  //   assign u_vendor_if.tck = tck;   // + tms/trst_n/tdi/tdo wiring
  //   ...
  //   uvm_config_db#(virtual <vendor>_jtag_if)::set(
  //       null, "*", "vendor_jtag_vif", u_vendor_if);
  `include "ocah_jtag_vendor_if.svh"
`endif

endinterface : ocah_jtag_if
