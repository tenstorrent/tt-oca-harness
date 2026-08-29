// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP functional-coverage module (the DTP_FCOV.adoc collection point).
//
// One passive, signal-driven module shared by both DTP flows: the cocotb and
// SV-UVM shapes of dtp_uvm_top instantiate it identically outside the UVM
// harness region, so the same coverage source serves Verilator and the
// commercial simulators.
//
// Two collection layers per DTP_FCOV.adoc:
//   * Labeled `OCAH_FCOV_COVER cover-property points — live in every flow;
//     under Verilator they form the public-CI functional-coverage database
//     (coverage.dat user points via --coverage-user).
//   * SV covergroups under `ifndef VERILATOR — commercial-simulator closure
//     (Verilator cannot compile covergroups; the public build defines
//     VERILATOR explicitly).
//
// Scenario-area sections (JTAG core, JTAG2AXI/OTP, debug TDR, scan/STAP,
// cross-trigger) are populated by their owning changes; this file carries the
// shared event decode and the per-boundary liveness points.

`include "ocah_fcov_macros.svh"

module dtp_fcov (
    input wire logic        tck_i,
    input wire logic        tms_i,
    input wire logic        trst_ni,
    input wire logic [15:0] tap_state_i,     // one-hot jtag_tap_pkg::tap_state_e
    input wire logic [63:0] inst_decoded_i   // one-hot decoded IR
);

  // ------------------------------------------------------------------
  // Shared event decode. The documented Python-side sampling boundaries
  // (completed IR scan, completed DR scan) map onto the UPDATE_* one-hot
  // TAP states; per-area transaction events are wired in by each section.
  // ------------------------------------------------------------------
  wire logic in_reset  = (trst_ni !== 1'b1);
  wire logic update_ir = (tap_state_i == jtag_tap_pkg::UPDATE_IR);
  wire logic update_dr = (tap_state_i == jtag_tap_pkg::UPDATE_DR);

  // ------------------------------------------------------------------
  // Scan-boundary liveness points: one per documented boundary, proving
  // the collection path end to end in every flow.
  // ------------------------------------------------------------------
  `OCAH_FCOV_COVER(c_completed_ir_scan, update_ir, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_completed_dr_scan, update_dr, tck_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups. Scenario-area covergroups are added
  // here by their owning sections; this one mirrors the liveness points.
  // ------------------------------------------------------------------
  covergroup cg_scan_boundary @(posedge tck_i);
    option.per_instance = 1;
    cp_boundary : coverpoint {update_ir, update_dr} iff (!in_reset) {
      bins ir_scan = {2'b10};
      bins dr_scan = {2'b01};
    }
  endgroup

  cg_scan_boundary u_cg_scan_boundary = new();
`endif

endmodule : dtp_fcov
