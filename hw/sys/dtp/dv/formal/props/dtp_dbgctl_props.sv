// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Formal properties for the DEBUG_CONTROL register: the four read-write control bits that change
// only on an Update-DR of this TDR, the read-only bit that captures the synchronized CLA
// clock-stop status, and the outputs that mirror the update register. Attached to
// jtag_debug_ctrl_reg by dtp_dbgctl_bind.sv and checked with dtp as the formal top. Every property
// body is a boolean over current and one-cycle-past values
// (hw/common/dv/docs/formal-property-style.adoc).
//
// The update register is a negedge flop; the select and update enables it sees at that negedge
// are the values sampled at the following posedge. The scan register is a posedge flop with no
// reset, so its captured value is checked one edge after the capture.

`include "ocah_fv_macros.svh"

module dtp_dbgctl_props (
  input logic       tck_i,               // scan_ctrl_i.tck
  input logic       rst_ni,              // scan_ctrl_i.rst_n
  input logic       select_i,            // scan_ctrl_i.select
  input logic       capture_en_i,        // scan_ctrl_i.capture_en
  input logic       update_en_i,         // scan_ctrl_i.update_en
  input logic       cla_clock_stop_i,    // cla_clock_stop_i
  input logic       cla_clock_stop_sync_i, // cla_clock_stop_sync
  input logic [4:0] update_q_i,          // debug_ctrl_reg_q
  input logic [4:0] scan_data_i,         // u_debug_ctrl_scan_reg.scan_data
  input logic       jtag_clock_stop_i,   // jtag_clock_stop_o
  input logic       cla_clock_stop_en_i, // cla_clock_stop_en_o
  input logic       boot_stall_ovrd_i,   // boot_stall_ovrd_o
  input logic       boot_stall_i         // boot_stall_o
);

  // verilog_format: off
  `OCAH_FV_INITIAL_RESET(tck_i, rst_ni)

  `OCAH_FV_ASSERT(ast_dbgctl_rw_bits_hold,
                  `OCAH_FV_IMPLIES($past(rst_ni) && !(select_i && update_en_i),
                                   update_q_i[3:0] == $past(update_q_i[3:0])),
                  tck_i, rst_ni)
  `OCAH_FV_ASSERT(ast_dbgctl_ro_bit_captures_status,
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(select_i && capture_en_i),
                                   scan_data_i[4] == $past(cla_clock_stop_sync_i) &&
                                   scan_data_i[3:0] == $past(update_q_i[3:0])),
                  tck_i, rst_ni)
  `OCAH_FV_ASSERT(ast_dbgctl_outputs_follow_update_reg,
                  jtag_clock_stop_i == update_q_i[3] && cla_clock_stop_en_i == update_q_i[2] &&
                  boot_stall_ovrd_i == update_q_i[1] && boot_stall_i == update_q_i[0],
                  tck_i, rst_ni)

  `OCAH_FV_COVER(cov_dbgctl_jtag_stop_without_cla,
                 jtag_clock_stop_i && !cla_clock_stop_i, tck_i, rst_ni)
  `OCAH_FV_COVER(cov_dbgctl_cla_without_jtag_stop,
                 cla_clock_stop_sync_i && !jtag_clock_stop_i, tck_i, rst_ni)
  `OCAH_FV_COVER(cov_dbgctl_status_captured,
                 $past(select_i && capture_en_i) && scan_data_i[4], tck_i, rst_ni)
  `OCAH_FV_COVER(cov_dbgctl_boot_stall_ovrd_stall_high,
                 boot_stall_ovrd_i && boot_stall_i, tck_i, rst_ni)
  `OCAH_FV_COVER(cov_dbgctl_boot_stall_ovrd_stall_low,
                 boot_stall_ovrd_i && !boot_stall_i, tck_i, rst_ni)
  // verilog_format: on

endmodule : dtp_dbgctl_props
