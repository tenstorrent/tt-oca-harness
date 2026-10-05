// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for STAP selection and the debug-disable gating of the STAP chain: the PTAP
// 3DCR select and TDO source, each jtag_stap with its 3DCR and disable mask, the stap_host return
// path, and the dbg_disable_i synchronizers. Attached to jtag_intf_unit by dtp_stap_bind.sv, which
// packs the per-STAP signals into vectors in chain order (I/O, SMC, SEP, extra), and checked with
// dtp as the formal top. Every property body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc).
//
// A STAP's disable input is the synchronizer output, a tck posedge flop, so the value sampled at
// a posedge is the one that gated the 3DCR update at the negedge before it. The 3DCR reset gate
// changes only at negedges, so a gate sampled high at two consecutive posedges was high
// throughout the cycle between them.

`include "ocah_fv_macros.svh"

module dtp_stap_props
  import prim_jtag_pkg::*;
  import jtag_tap_pkg::*;
#(
  parameter int unsigned NUM_STAPS = 4,
  parameter int unsigned NUM_DISABLE = 11
) (
  input logic                   tck_i,               // ptap_client_tap_ctrl_i.tck
  input logic                   trst_ni,             // ptap_host_tap_ctrl.trst_n, the combined reset
  input logic                   pwr_on_rst_ni,
  input logic                   client_tms_i,        // ptap_host_tap_ctrl.tms
  input logic                   shift_en_i,          // ptap_stap_host_scan_ctrl.shift_en
  // dbg_disable_i synchronizers, one per field
  input logic [NUM_DISABLE-1:0] dbg_disable_i,       // dbg_disable_bits
  input logic [NUM_DISABLE-1:0] dbg_disable_stage1_i,// u_dbg_disable_sync_n0_scan.intq
  input logic [NUM_DISABLE-1:0] dbg_disable_q_i,     // dbg_disable_bits_q_n0_scan
  // Per-STAP vectors in chain order
  input logic [NUM_STAPS-1:0]   stap_disable_i,      // security_disable_i
  input logic [NUM_STAPS-1:0]   stap_sel_i,          // stap_sel, the masked select
  input logic [NUM_STAPS-1:0]   stap_sel_int_i,      // stap_sel_int, the 3DCR select bit
  input logic [NUM_STAPS-1:0]   stap_tms_hold_i,     // tms_hold
  input logic [NUM_STAPS-1:0]   stap_config_hold_i,  // config_hold
  input logic [NUM_STAPS-1:0]   stap_3dcr_gate_ni,   // rst_n_gate
  input logic [NUM_STAPS-1:0]   host_tms_i,          // host_tap_ctrl_o.tms
  input logic [NUM_STAPS-1:0]   host_tdo_i,          // host_tdo_o
  input logic [NUM_STAPS-1:0]   host_tdo_oen_i,      // host_tdo_oen_o
  // PTAP 3DCR select and TDO source
  input logic                   ptap_stap_select_i,  // u_jtag_ptap.stap_select
  input logic                   ptap_tdo_mux_i,      // u_jtag_ptap.tdo_mux
  input logic                   ptap_zlb_tdr_mux_i,  // u_jtag_ptap.zlb_tdr_mux
  input logic                   ptap_stap_scan_in_i, // ptap_stap_host_scan_in
  // stap_host return path
  input logic                   stap_host_disable_i, // dbg_disable_q.stap_host
  input logic                   chain_out_i,         // extra_stap_scan_out[NUM_EXTRA_STAPS]
  input logic                   stap_host_scan_in_i, // stap_host_scan_in_i
  input jtag_scan_ctrl_t        ptap_stap_ctrl_i,    // ptap_stap_host_scan_ctrl
  input jtag_scan_ctrl_t        stap_host_ctrl_i     // stap_host_scan_ctrl_o
);

  // The host scan control with every enable and state flag cleared, the disabled shape.
  jtag_scan_ctrl_t ptap_stap_ctrl_quiet;
  always_comb begin
    ptap_stap_ctrl_quiet                  = ptap_stap_ctrl_i;
    ptap_stap_ctrl_quiet.select           = 1'b0;
    ptap_stap_ctrl_quiet.capture_en       = 1'b0;
    ptap_stap_ctrl_quiet.shift_en         = 1'b0;
    ptap_stap_ctrl_quiet.update_en        = 1'b0;
    ptap_stap_ctrl_quiet.runbist          = 1'b0;
    ptap_stap_ctrl_quiet.test_logic_reset = 1'b0;
    ptap_stap_ctrl_quiet.run_test_idle    = 1'b0;
  end

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, trst_ni)

  for (genvar k = 0; k < NUM_STAPS; k++) begin : gen_stap
    `OCAH_FV_ASSERT(ast_stap_disable_forces_sel_low,
                    stap_sel_i[k] == (stap_disable_i[k] ? 1'b0 : stap_sel_int_i[k]),
                    tck_i, trst_ni)
    `OCAH_FV_ASSERT(ast_stap_disable_tdo_low,
                    `OCAH_FV_IMPLIES(stap_disable_i[k], !host_tdo_i[k]),
                    tck_i, trst_ni)
    `OCAH_FV_ASSERT(ast_stap_disable_blocks_3dcr_update,
                    `OCAH_FV_IMPLIES($past(trst_ni) && stap_disable_i[k] &&
                                     stap_3dcr_gate_ni[k] && $past(stap_3dcr_gate_ni[k]),
                                     stap_tms_hold_i[k] == $past(stap_tms_hold_i[k]) &&
                                     stap_sel_int_i[k] == $past(stap_sel_int_i[k]) &&
                                     stap_config_hold_i[k] == $past(stap_config_hold_i[k])),
                    tck_i, trst_ni)
    `OCAH_FV_ASSERT(ast_stap_unselected_parks_tms,
                    host_tms_i[k] == (stap_sel_i[k] ? client_tms_i : stap_tms_hold_i[k]),
                    tck_i, trst_ni)
    `OCAH_FV_ASSERT(ast_stap_tdo_oen_only_when_selected_shifting,
                    host_tdo_oen_i[k] == (stap_sel_i[k] && shift_en_i),
                    tck_i, trst_ni)
    `OCAH_FV_COVER(cov_stap_selected, stap_sel_i[k], tck_i, trst_ni)
    `OCAH_FV_COVER(cov_stap_disabled_while_selected,
                   stap_disable_i[k] && stap_sel_int_i[k], tck_i, trst_ni)
  end

  // ---- stap_host return path and the PTAP TDO source ----------------------------------------
  `OCAH_FV_ASSERT(ast_stap_host_disable_loops_back,
                  ptap_stap_scan_in_i ==
                  (stap_host_disable_i ? chain_out_i : stap_host_scan_in_i) &&
                  stap_host_ctrl_i ==
                  (stap_host_disable_i ? ptap_stap_ctrl_quiet : ptap_stap_ctrl_i),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_ptap_stap_select_routes_tdo,
                  ptap_tdo_mux_i ==
                  (ptap_stap_select_i ? ptap_stap_scan_in_i : ptap_zlb_tdr_mux_i),
                  tck_i, trst_ni)
  `OCAH_FV_ASSERT(ast_stap_chain_quiet_unselected,
                  `OCAH_FV_IMPLIES(!ptap_stap_select_i,
                                   !ptap_stap_ctrl_i.select && !ptap_stap_ctrl_i.capture_en &&
                                   !ptap_stap_ctrl_i.shift_en && !ptap_stap_ctrl_i.update_en),
                  tck_i, trst_ni)

  // ---- dbg_disable_i synchronizers: reset to disabled, two tck edges of latency --------------
  `OCAH_FV_ASSERT(ast_dbg_disable_sync_fail_closed,
                  `OCAH_FV_IMPLIES(!pwr_on_rst_ni,
                                   dbg_disable_q_i == '1 && dbg_disable_stage1_i == '1) &&
                  `OCAH_FV_IMPLIES($past(pwr_on_rst_ni) && pwr_on_rst_ni,
                                   dbg_disable_stage1_i == $past(dbg_disable_i) &&
                                   dbg_disable_q_i == $past(dbg_disable_stage1_i)),
                  tck_i, 1'b1)

  // ---- Covers -------------------------------------------------------------------------------
  `OCAH_FV_COVER(cov_stap_host_disabled_during_shift,
                 stap_host_disable_i && shift_en_i, tck_i, trst_ni)
  `OCAH_FV_COVER(cov_stap_host_enabled_during_shift,
                 !stap_host_disable_i && shift_en_i && ptap_stap_select_i, tck_i, trst_ni)
  // verilog_format: on

endmodule : dtp_stap_props
