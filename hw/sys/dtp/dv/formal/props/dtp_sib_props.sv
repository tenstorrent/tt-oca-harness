// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the iJTAG SIB network and its debug-disable gating: the three
// prim_jtag_sib_mux_post instances (DFT secure, DFT non-secure, DFD) and their chain order.
// Attached to jtag_intf_unit by dtp_sib_bind.sv, which packs the per-SIB signals into vectors in
// chain order, and checked with dtp as the formal top. Every property body is a boolean over
// current and one-cycle-past values (hw/common/dv/docs/formal-property-style.adoc).
//
// The properties run on the scan reset of the iJTAG chain, so they are disabled while the TAP is
// in Test-Logic-Reset, where every SIB bit is held at zero. A SIB's disable input is the
// synchronizer output, a tck posedge flop, so the value sampled at a posedge is the one that
// gated the SIB update at the negedge before it.

`include "ocah_fv_macros.svh"

module dtp_sib_props
#(
  parameter int unsigned NUM_SIBS = 3
) (
  input logic                tck_i,                // ptap_ijtag_host_scan_ctrl.tck
  input logic                rst_ni,               // ptap_ijtag_host_scan_ctrl.rst_n
  input logic                client_select_i,      // ptap_ijtag_host_scan_ctrl.select
  input logic                client_capture_en_i,  // ptap_ijtag_host_scan_ctrl.capture_en
  input logic                client_shift_en_i,    // ptap_ijtag_host_scan_ctrl.shift_en
  input logic                client_update_en_i,   // ptap_ijtag_host_scan_ctrl.update_en
  input logic                ptap_scan_out_i,      // ptap_ijtag_host_scan_out, into the chain
  input logic                ptap_scan_in_i,       // ptap_ijtag_host_scan_in, out of the chain
  // Per-SIB vectors in chain order
  input logic [NUM_SIBS-1:0] sib_disable_i,        // security_disable_i
  input logic [NUM_SIBS-1:0] sib_en_i,             // sib_en, the update register bit
  input logic [NUM_SIBS-1:0] sib_en_masked_i,      // sib_en_masked
  input logic [NUM_SIBS-1:0] sib_scan_out_i,       // scan_reg_scan_out, the SIB's own bit
  input logic [NUM_SIBS-1:0] client_scan_in_i,     // client_scan_in_i
  input logic [NUM_SIBS-1:0] client_scan_out_i,    // client_scan_out_o
  input logic [NUM_SIBS-1:0] host_scan_in_i,       // host_scan_in_i
  input logic [NUM_SIBS-1:0] host_scan_out_i,      // host_scan_out_o
  input logic [NUM_SIBS-1:0] host_capture_en_i,    // host_scan_ctrl_o.capture_en
  input logic [NUM_SIBS-1:0] host_shift_en_i,      // host_scan_ctrl_o.shift_en
  input logic [NUM_SIBS-1:0] host_update_en_i,     // host_scan_ctrl_o.update_en
  input logic [NUM_SIBS-1:0] host_select_i         // host_scan_ctrl_o.select
);

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, rst_ni)

  for (genvar k = 0; k < NUM_SIBS; k++) begin : gen_sib
    `OCAH_FV_ASSERT(ast_sib_disable_forces_en_low,
                    sib_en_masked_i[k] == (sib_disable_i[k] ? 1'b0 : sib_en_i[k]) &&
                    `OCAH_FV_IMPLIES(sib_disable_i[k], !host_select_i[k]),
                    tck_i, rst_ni)
    `OCAH_FV_ASSERT(ast_sib_disable_blocks_update,
                    `OCAH_FV_IMPLIES($past(rst_ni) && sib_disable_i[k],
                                     sib_en_i[k] == $past(sib_en_i[k])),
                    tck_i, rst_ni)
    `OCAH_FV_ASSERT(ast_sib_disable_host_quiet,
                    `OCAH_FV_IMPLIES(sib_disable_i[k],
                                     !host_capture_en_i[k] && !host_shift_en_i[k] &&
                                     !host_update_en_i[k] && !host_select_i[k] &&
                                     !host_scan_out_i[k]),
                    tck_i, rst_ni)
    `OCAH_FV_ASSERT(ast_sib_open_routes_host,
                    client_scan_out_i[k] ==
                    (sib_en_masked_i[k] ? host_scan_in_i[k] : sib_scan_out_i[k]),
                    tck_i, rst_ni)
    `OCAH_FV_ASSERT(ast_sib_host_ctrl_follows_client,
                    `OCAH_FV_IMPLIES(!sib_disable_i[k],
                                     host_capture_en_i[k] ==
                                     (client_capture_en_i && client_select_i) &&
                                     host_shift_en_i[k] ==
                                     (client_shift_en_i && client_select_i) &&
                                     host_update_en_i[k] ==
                                     (client_update_en_i && client_select_i) &&
                                     host_select_i[k] == (client_select_i && sib_en_i[k]) &&
                                     host_scan_out_i[k] == sib_scan_out_i[k]),
                    tck_i, rst_ni)
    `OCAH_FV_COVER(cov_sib_disabled_while_open, sib_disable_i[k] && sib_en_i[k], tck_i, rst_ni)
  end

  // The chain runs from the PTAP through the secure, non-secure and DFD SIBs back to the PTAP.
  `OCAH_FV_ASSERT(ast_sib_chain_order,
                  client_scan_in_i[0] == ptap_scan_out_i &&
                  client_scan_in_i[1] == client_scan_out_i[0] &&
                  client_scan_in_i[2] == client_scan_out_i[1] &&
                  ptap_scan_in_i == client_scan_out_i[2],
                  tck_i, rst_ni)

  for (genvar p = 0; p < (1 << NUM_SIBS); p++) begin : gen_sib_pattern
    `OCAH_FV_COVER(cov_sib_pattern, sib_en_i == NUM_SIBS'(p), tck_i, rst_ni)
  end
  // verilog_format: on

endmodule : dtp_sib_props
