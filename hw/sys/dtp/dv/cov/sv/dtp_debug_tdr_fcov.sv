// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Debug-TDR functional coverage (tmp_ic_reset_cg, debug_control_cg,
// caps_tdr_cg).
//
// One instance in the shared tb_top serves both flows. Most bins derive from
// the flattened TDR outputs (IC_RESET slices, boot stall, clock stop) and the
// committed-instruction decode; the TMP state machine and the DEBUG_CONTROL
// clock-stop contributions come through hierarchical references. The TMP
// read value and the capability-TDR write patterns are reconstructed from
// the serial TDI/TDO streams during Shift-DR — at every TCK rising edge
// inside Shift-DR the DUT samples TDI and drives the next TDO bit, so a
// per-scan accumulator indexed from Capture-DR sees exactly the shifted
// data.
//
// Stimulus-intent bins from DTP_FCOV.adoc (IC_RESET pattern source, seeded
// random request masks) are not signal-observable and stay with the test
// layer; the document reconciliation maps them.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables.

`include "ocah_fcov_macros.svh"

module dtp_debug_tdr_fcov (
  input wire        tck_i,
  input wire        tdi_i,
  input wire        tdo_i,
  input wire        trst_ni,
  input wire        clk_i,
  input wire        rst_ni,
  input wire [15:0] tap_state_i,
  input wire [63:0] inst_decoded_i,

  // Flattened TDR outputs (TCK domain)
  input wire        ic_reset_smc_ovrd_i,
  input wire        ic_reset_smc_ctrl_n_i,
  input wire        ic_reset_sep_ovrd_i,
  input wire        ic_reset_sep_ctrl_n_i,
  input wire        ic_reset_ext_ovrd_i,
  input wire        ic_reset_ext_ctrl_n_i,
  input wire        boot_stall_ovrd_i,
  input wire        boot_stall_i,
  input wire        stop_clks_i,
  input wire        cla_clock_stop_en_i,
  input wire [8:0]  clk_stop_req_i,

  // Hierarchical references (TMP unit and DEBUG_CONTROL contributions)
  input wire        tmp_state_i,           // 0 = off, 1 = persistence on
  input wire [1:0]  tmp_status_reg_i,      // [1] persistence, [0] escape arm
  input wire        tmp_escape_cond_i,     // BYPASS double-load escape pulse
  input wire        jtag_clock_stop_i,     // DEBUG_CONTROL JTAG stop
  input wire        cla_clock_stop_i       // OR of CLA stop requests
);

  // ------------------------------------------------------------------
  // Decode masks (jtag_inst_reg_pkg one-hot bit positions).
  // ------------------------------------------------------------------
  localparam logic [63:0] TmpStatusTdr = 64'h1 << 6'h0C;
  localparam logic [63:0] IcResetTdr = 64'h1 << 6'h0D;
  localparam logic [63:0] DebugControlTdr = 64'h1 << 6'h18;
  localparam logic [63:0] JtagCapsTdr = 64'h1 << 6'h19;
  localparam logic [63:0] SmcOtpCapsTdr = 64'h1 << 6'h1B;
  localparam logic [63:0] SepOtpCapsTdr = 64'h1 << 6'h21;
  localparam logic [63:0] SmcCapsTdr = 64'h1 << 6'h27;
  localparam logic [63:0] AnyCapsTdr = JtagCapsTdr | SmcOtpCapsTdr | SepOtpCapsTdr | SmcCapsTdr;
  localparam logic [63:0] IdcodeInstr = 64'h1 << 6'h01;
  localparam logic [63:0] BypassInstr = (64'h1 << 6'h00) | (64'h1 << 6'h3F);

  // ------------------------------------------------------------------
  // Common scan decode and the per-scan serial accumulator.
  // ------------------------------------------------------------------
  wire in_reset = (trst_ni !== 1'b1);
  logic [15:0] tap_state_q;
  always_ff @(posedge tck_i) tap_state_q <= tap_state_i;
  wire [15:0] tap_state_prev = tap_state_q;
  wire dr_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_DR) && !in_reset;
  wire ir_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_IR) && !in_reset;
  wire in_capture_dr = (tap_state_i == jtag_tap_pkg::CAPTURE_DR);
  wire in_shift_dr = (tap_state_i == jtag_tap_pkg::SHIFT_DR);

  logic [63:0] tdi_accum_q;
  logic [1:0] tdo_head_q;
  logic [6:0] shift_count_q;
  always_ff @(posedge tck_i) begin
    if (in_capture_dr) begin
      tdi_accum_q <= '0;
      tdo_head_q <= '0;
      shift_count_q <= '0;
    end else if (in_shift_dr) begin
      if (shift_count_q < 7'd64) begin
        tdi_accum_q[shift_count_q[5:0]] <= tdi_i;
      end
      if (shift_count_q < 7'd2) begin
        tdo_head_q[shift_count_q[0]] <= tdo_i;
      end
      if (shift_count_q != 7'h7F) begin
        shift_count_q <= shift_count_q + 7'd1;
      end
    end
  end

  wire [63:0] shifted_mask =
      (shift_count_q >= 7'd64) ? {64{1'b1}} : ((64'h1 << shift_count_q[5:0]) - 1);
  wire [63:0] shifted_bits = tdi_accum_q & shifted_mask;

  // ------------------------------------------------------------------
  // tmp_ic_reset_cg — TMP persistence, read value, escape, and IC_RESET.
  // ------------------------------------------------------------------
  wire tmp_sel = |(inst_decoded_i & TmpStatusTdr);
  wire tmp_read_valid = dr_committed && tmp_sel && (shift_count_q >= 7'd2);
  wire tmp_persistence_off_e = !in_reset && !tmp_state_i;
  wire tmp_persistence_on_e = !in_reset && tmp_state_i;
  wire tmp_value_zero_e = tmp_read_valid && (tdo_head_q == 2'b00);
  wire tmp_value_persist_e = tmp_read_valid && tdo_head_q[1];
  wire tmp_value_armed_e = tmp_read_valid && tdo_head_q[0];
  wire tmp_escape_unarmed_e = dr_committed && tmp_sel && !tmp_status_reg_i[0];
  wire tmp_escape_armed_e = dr_committed && tmp_sel && tmp_status_reg_i[0];
  wire tmp_escape_observed_e = !in_reset && tmp_escape_cond_i;
  `OCAH_FCOV_COVER(c_tmp_persistence_reset_off, tmp_persistence_off_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_persistence_clamp_hold_on, tmp_persistence_on_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_read_value_zero, tmp_value_zero_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_read_value_persistence, tmp_value_persist_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_read_value_escape_armed, tmp_value_armed_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_escape_unarmed, tmp_escape_unarmed_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_escape_armed, tmp_escape_armed_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_escape_observed, tmp_escape_observed_e, tck_i, in_reset)

  // TMP persistence across chip reset: the state survives a system-reset
  // assertion (sampled in the system-clock domain).
  logic sys_rst_nq;
  always_ff @(posedge clk_i) sys_rst_nq <= rst_ni;
  wire sys_rst_fell_e = sys_rst_nq && !rst_ni;
  wire tmp_chip_reset_preserved_e = sys_rst_fell_e && tmp_state_i;
  `OCAH_FCOV_COVER(c_tmp_persistence_chip_reset_preserved, tmp_chip_reset_preserved_e, clk_i, 1'b0)
  logic tmp_escape_seen_q;
  always_ff @(posedge tck_i) begin
    if (tmp_escape_cond_i) tmp_escape_seen_q <= 1'b1;
    else if (!tmp_state_i) tmp_escape_seen_q <= 1'b0;
  end
  wire tmp_escape_release_e = !tmp_state_i && tmp_escape_seen_q;
  `OCAH_FCOV_COVER(c_tmp_persistence_bypass_escape_release, tmp_escape_release_e, tck_i, in_reset)

  // IC_RESET slices, override classes, and TLR/TRST hold behavior.
  wire ic_sel = |(inst_decoded_i & IcResetTdr);
  logic ic_smc_ovrd_q, ic_smc_ctrl_q, ic_sep_ovrd_q, ic_sep_ctrl_q;
  logic ic_ext_ovrd_q, ic_ext_ctrl_q;
  always_ff @(posedge tck_i) begin
    ic_smc_ovrd_q <= ic_reset_smc_ovrd_i;
    ic_smc_ctrl_q <= ic_reset_smc_ctrl_n_i;
    ic_sep_ovrd_q <= ic_reset_sep_ovrd_i;
    ic_sep_ctrl_q <= ic_reset_sep_ctrl_n_i;
    ic_ext_ovrd_q <= ic_reset_ext_ovrd_i;
    ic_ext_ctrl_q <= ic_reset_ext_ctrl_n_i;
  end
  wire ic_slice_smc_e = (ic_reset_smc_ovrd_i != ic_smc_ovrd_q)
      || (ic_reset_smc_ctrl_n_i != ic_smc_ctrl_q);
  wire ic_slice_sep_e = (ic_reset_sep_ovrd_i != ic_sep_ovrd_q)
      || (ic_reset_sep_ctrl_n_i != ic_sep_ctrl_q);
  wire ic_slice_ext_e = (ic_reset_ext_ovrd_i != ic_ext_ovrd_q)
      || (ic_reset_ext_ctrl_n_i != ic_ext_ctrl_q);
  wire ic_ovrd_any = ic_reset_smc_ovrd_i || ic_reset_sep_ovrd_i
      || ic_reset_ext_ovrd_i;
  wire ic_override_disabled_e = dr_committed && ic_sel && !ic_ovrd_any;
  wire ic_override_enabled_e = dr_committed && ic_sel && ic_ovrd_any;
  wire ic_reset_asserted_e = (ic_reset_smc_ovrd_i && !ic_reset_smc_ctrl_n_i)
      || (ic_reset_sep_ovrd_i && !ic_reset_sep_ctrl_n_i)
      || (ic_reset_ext_ovrd_i && !ic_reset_ext_ctrl_n_i);
  wire ic_reset_deasserted_e = (ic_reset_smc_ovrd_i && ic_reset_smc_ctrl_n_i)
      || (ic_reset_sep_ovrd_i && ic_reset_sep_ctrl_n_i)
      || (ic_reset_ext_ovrd_i && ic_reset_ext_ctrl_n_i);
  `OCAH_FCOV_COVER(c_ic_reset_slice_smc, ic_slice_smc_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_slice_sep, ic_slice_sep_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_slice_ext, ic_slice_ext_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_override_disabled, ic_override_disabled_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_override_enabled, ic_override_enabled_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_asserted, ic_reset_asserted_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_deasserted, ic_reset_deasserted_e, tck_i, in_reset)

  logic ic_ovrd_any_q, ic_ovrd_any_qq, tlr_entry_q;
  always_ff @(posedge tck_i) begin
    ic_ovrd_any_q <= ic_ovrd_any;
    ic_ovrd_any_qq <= ic_ovrd_any_q;
    tlr_entry_q <= (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET)
        && (tap_state_prev != jtag_tap_pkg::TEST_LOGIC_RESET);
  end
  // At the edge after a TLR entry the previous-cycle override state tells
  // whether the TDR held (reset_hold=1) or restored defaults (reset_hold=0).
  wire ic_hold_tlr_preserve_e = tlr_entry_q && ic_ovrd_any_qq && ic_ovrd_any;
  wire ic_hold_tlr_restore_e = tlr_entry_q && ic_ovrd_any_qq && !ic_ovrd_any;
  wire ic_hold_trst_restore_e = !trst_ni && ic_ovrd_any_q;
  `OCAH_FCOV_COVER(c_ic_reset_hold_tlr_preserve, ic_hold_tlr_preserve_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_hold_tlr_restore, ic_hold_tlr_restore_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_hold_trst_restore, ic_hold_trst_restore_e, tck_i, 1'b0)

  // ------------------------------------------------------------------
  // debug_control_cg — boot stall, clock-stop request/readback/output.
  // ------------------------------------------------------------------
  wire dbgctl_sel = |(inst_decoded_i & DebugControlTdr);
  wire boot_combo_00_e = !in_reset && !boot_stall_ovrd_i && !boot_stall_i;
  wire boot_combo_01_e = !in_reset && !boot_stall_ovrd_i && boot_stall_i;
  wire boot_combo_10_e = !in_reset && boot_stall_ovrd_i && !boot_stall_i;
  wire boot_combo_11_e = !in_reset && boot_stall_ovrd_i && boot_stall_i;
  wire cla_active = cla_clock_stop_en_i && cla_clock_stop_i;
  wire boot_active = boot_stall_ovrd_i;
  wire boot_standalone_e = boot_active && !jtag_clock_stop_i && !cla_active;
  wire boot_with_jtag_stop_e = boot_active && jtag_clock_stop_i;
  wire boot_with_cla_en_e = boot_active && cla_clock_stop_en_i;
  wire boot_with_both_e = boot_active && jtag_clock_stop_i && cla_clock_stop_en_i;
  `OCAH_FCOV_COVER(c_boot_stall_ovrd0_stall0, boot_combo_00_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_ovrd0_stall1, boot_combo_01_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_ovrd1_stall0, boot_combo_10_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_ovrd1_stall1, boot_combo_11_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_standalone, boot_standalone_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_with_jtag_stop, boot_with_jtag_stop_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_with_cla_en, boot_with_cla_en_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_with_both, boot_with_both_e, tck_i, in_reset)

  logic jtag_stop_q, stop_clks_q;
  always_ff @(posedge tck_i) begin
    jtag_stop_q <= jtag_clock_stop_i;
    stop_clks_q <= stop_clks_i;
  end
  wire jtag_stop_asserted_e = jtag_clock_stop_i && !jtag_stop_q;
  wire jtag_stop_deasserted_e = !jtag_clock_stop_i && jtag_stop_q;
  wire cla_en_disabled_e = !in_reset && !cla_clock_stop_en_i;
  wire cla_en_enabled_e = !in_reset && cla_clock_stop_en_i;
  `OCAH_FCOV_COVER(c_jtag_clock_stop_asserted, jtag_stop_asserted_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag_clock_stop_deasserted, jtag_stop_deasserted_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_clock_stop_en_disabled, cla_en_disabled_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_clock_stop_en_enabled, cla_en_enabled_e, tck_i, in_reset)

  wire [3:0] req_count = 4'($countones(clk_stop_req_i));
  wire dbgctl_capture = in_capture_dr && dbgctl_sel && !in_reset;
  wire cla_readback_none_e = dbgctl_capture && (req_count == 4'd0);
  wire cla_readback_one_e = dbgctl_capture && (req_count == 4'd1);
  wire cla_readback_multi_e = dbgctl_capture && (req_count >= 4'd2);
  `OCAH_FCOV_COVER(c_cla_readback_no_request, cla_readback_none_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_readback_one_request, cla_readback_one_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_readback_multiple_requests, cla_readback_multi_e, tck_i, in_reset)

  // Clock-stop request source: each single request bit plus multi-bit masks
  // (sampled in the request clock domain).
  wire clk_in_reset = (rst_ni !== 1'b1);
  `define DTP_FCOV_REQ_BIT(__label, __idx)                                     \
    wire __label``_e = (clk_stop_req_i == (9'h1 << (__idx)));            \
    `OCAH_FCOV_COVER(__label, __label``_e, clk_i, clk_in_reset)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_0, 0)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_1, 1)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_2, 2)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_3, 3)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_4, 4)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_5, 5)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_6, 6)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_7, 7)
  `DTP_FCOV_REQ_BIT(c_clk_stop_req_bit_8, 8)
  `undef DTP_FCOV_REQ_BIT
  wire req_none_e = !clk_in_reset && (clk_stop_req_i == '0);
  wire req_multi_e = !clk_in_reset && ($countones(clk_stop_req_i) >= 2);
  `OCAH_FCOV_COVER(c_clk_stop_req_none, req_none_e, clk_i, clk_in_reset)
  `OCAH_FCOV_COVER(c_clk_stop_req_multi_mask, req_multi_e, clk_i, clk_in_reset)

  wire stop_out_jtag_only_e = stop_clks_i && jtag_clock_stop_i && !cla_active;
  wire stop_out_cla_only_e = stop_clks_i && !jtag_clock_stop_i && cla_active;
  wire stop_out_combined_e = stop_clks_i && jtag_clock_stop_i && cla_active;
  wire stop_out_released_e = !stop_clks_i && stop_clks_q;
  `OCAH_FCOV_COVER(c_clock_stop_output_jtag_only, stop_out_jtag_only_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_clock_stop_output_cla_only, stop_out_cla_only_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_clock_stop_output_combined, stop_out_combined_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_clock_stop_output_released, stop_out_released_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // caps_tdr_cg — capability-TDR accesses, re-reads, write patterns, and
  // the preceding-instruction context. The parameter-derived field bins
  // (JTAG_CAPS fields, bus type, geometry) are carried by the commercial
  // covergroup on the per-TDR capture events.
  // ------------------------------------------------------------------
  wire caps_jtag_sel = |(inst_decoded_i & JtagCapsTdr);
  wire caps_smc_sel = |(inst_decoded_i & SmcCapsTdr);
  wire caps_smc_otp_sel = |(inst_decoded_i & SmcOtpCapsTdr);
  wire caps_sep_otp_sel = |(inst_decoded_i & SepOtpCapsTdr);
  wire caps_any_sel = |(inst_decoded_i & AnyCapsTdr);
  wire caps_capture = in_capture_dr && caps_any_sel && !in_reset;

  logic caps_seen_jtag_q, caps_seen_smc_q, caps_seen_smc_otp_q, caps_seen_sep_otp_q;
  // Two-stage committed-instruction history: at an IR commit the decode
  // already shows the NEW instruction, so the instruction that preceded the
  // current one is the previous commit's class.
  logic cur_instr_idcode_q, cur_instr_bypass_q;
  logic prev_instr_idcode_q, prev_instr_bypass_q;
  always_ff @(posedge tck_i) begin
    if (in_capture_dr && caps_jtag_sel) caps_seen_jtag_q <= 1'b1;
    if (in_capture_dr && caps_smc_sel) caps_seen_smc_q <= 1'b1;
    if (in_capture_dr && caps_smc_otp_sel) caps_seen_smc_otp_q <= 1'b1;
    if (in_capture_dr && caps_sep_otp_sel) caps_seen_sep_otp_q <= 1'b1;
    if (ir_committed) begin
      prev_instr_idcode_q <= cur_instr_idcode_q;
      prev_instr_bypass_q <= cur_instr_bypass_q;
      cur_instr_idcode_q <= |(inst_decoded_i & IdcodeInstr);
      cur_instr_bypass_q <= |(inst_decoded_i & BypassInstr);
    end
  end

  wire caps_read_jtag_e = in_capture_dr && caps_jtag_sel && !in_reset;
  wire caps_read_smc_e = in_capture_dr && caps_smc_sel && !in_reset;
  wire caps_read_smc_otp_e = in_capture_dr && caps_smc_otp_sel && !in_reset;
  wire caps_read_sep_otp_e = in_capture_dr && caps_sep_otp_sel && !in_reset;
  wire caps_reread_e = caps_capture
      && ((caps_jtag_sel && caps_seen_jtag_q) || (caps_smc_sel && caps_seen_smc_q)
          || (caps_smc_otp_sel && caps_seen_smc_otp_q)
          || (caps_sep_otp_sel && caps_seen_sep_otp_q));
  wire caps_after_idcode_e = caps_capture && prev_instr_idcode_q;
  wire caps_after_bypass_e = caps_capture && prev_instr_bypass_q;
  `OCAH_FCOV_COVER(c_caps_read_jtag_caps, caps_read_jtag_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_smc_jtag2axi_caps, caps_read_smc_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_smc_otp_jtag2axi_caps, caps_read_smc_otp_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_sep_otp_jtag2axi_caps, caps_read_sep_otp_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_repeated_read, caps_reread_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_after_idcode, caps_after_idcode_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_after_bypass, caps_after_bypass_e, tck_i, in_reset)

  wire caps_write_committed = dr_committed && caps_any_sel && (shift_count_q >= 7'd8);
  wire [63:0] alt_a = 64'hAAAA_AAAA_AAAA_AAAA & shifted_mask;
  wire [63:0] alt_5 = 64'h5555_5555_5555_5555 & shifted_mask;
  wire caps_wr_zero_e = caps_write_committed && (shifted_bits == '0);
  wire caps_wr_ones_e = caps_write_committed && (shifted_bits == shifted_mask);
  wire caps_wr_alt_e = caps_write_committed
      && ((shifted_bits == alt_a) || (shifted_bits == alt_5));
  wire caps_wr_random_e = caps_write_committed && (shifted_bits != '0)
      && (shifted_bits != shifted_mask) && (shifted_bits != alt_a)
      && (shifted_bits != alt_5);
  `OCAH_FCOV_COVER(c_caps_write_attempt_all_zero, caps_wr_zero_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_write_attempt_all_one, caps_wr_ones_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_write_attempt_alternating, caps_wr_alt_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_write_attempt_random, caps_wr_random_e, tck_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the cover-property bins.
  // ------------------------------------------------------------------
  // caps_reread_e is true only on the Capture-DR edge of a capability scan;
  // the covergroup samples at that scan's Update-DR commit and reads the
  // decision held from the capture.
  logic caps_reread_q;
  always_ff @(posedge tck_i) begin
    if (caps_capture) caps_reread_q <= caps_reread_e;
  end

  covergroup cg_tmp_ic_reset with function sample (
      logic tmp_on, logic [1:0] tmp_value, logic escape_armed, logic ovrd_any, logic asserted_any
  );
    option.per_instance = 1;
    cp_tmp_state: coverpoint tmp_on;
    cp_tmp_value: coverpoint tmp_value;
    cp_escape_armed: coverpoint escape_armed;
    cp_override: coverpoint ovrd_any;
    cp_asserted: coverpoint asserted_any;
  endgroup

  covergroup cg_debug_control with function sample (
      logic [1:0] boot_combo, logic jtag_stop, logic cla_en, logic [3:0] reqs, logic [1:0] stop_out
  );
    option.per_instance = 1;
    cp_boot: coverpoint boot_combo;
    cp_jtag_stop: coverpoint jtag_stop;
    cp_cla_en: coverpoint cla_en;
    cp_reqs: coverpoint reqs {bins none = {4'd0}; bins one = {4'd1}; bins multi = {[4'd2 : 4'd9]};}
    cp_stop_out: coverpoint stop_out {
      bins released = {2'b00};
      bins jtag_only = {2'b10};
      bins cla_only = {2'b01};
      bins combined = {2'b11};
    }
  endgroup

  covergroup cg_caps_tdr with function sample (
      logic [1:0] which, logic reread, logic after_idcode, logic after_bypass, logic [1:0] pattern
  );
    option.per_instance = 1;
    cp_register: coverpoint which {
      bins jtag_caps = {2'd0};
      bins smc_caps = {2'd1};
      bins smc_otp_caps = {2'd2};
      bins sep_otp_caps = {2'd3};
    }
    // Stability is a property of a repeated read; the single bin closes
    // on the capture-time decision held in caps_reread_q.
    cp_reread: coverpoint reread {
      bins repeated = {1'b1};
    }
    cp_after: coverpoint {
      after_idcode, after_bypass
    } {
      bins after_idcode_bin = {2'b10}; bins after_bypass_bin = {2'b01};
    }
    cp_pattern: coverpoint pattern {
      bins all_zero = {2'd0};
      bins all_one = {2'd1};
      bins alternating = {2'd2};
      bins deterministic_random = {2'd3};
    }
  endgroup

  cg_tmp_ic_reset u_cg_tmp_ic_reset = new();
  cg_debug_control u_cg_debug_control = new();
  cg_caps_tdr u_cg_caps_tdr = new();

  always_ff @(posedge tck_i) begin
    if (dr_committed && (tmp_sel || ic_sel)) begin
      u_cg_tmp_ic_reset.sample(tmp_state_i, tdo_head_q, tmp_status_reg_i[0], ic_ovrd_any,
                               ic_reset_asserted_e);
    end
    if (dr_committed && dbgctl_sel) begin
      u_cg_debug_control.sample({boot_stall_ovrd_i, boot_stall_i}, jtag_clock_stop_i,
                                cla_clock_stop_en_i, req_count, {
                                jtag_clock_stop_i && stop_clks_i, cla_active && stop_clks_i});
    end
    if (caps_write_committed) begin
      u_cg_caps_tdr.sample(
          caps_jtag_sel ? 2'd0 : (caps_smc_sel ? 2'd1 : (caps_smc_otp_sel ? 2'd2 : 2'd3)),
          caps_reread_q, prev_instr_idcode_q, prev_instr_bypass_q,
          caps_wr_zero_e ? 2'd0 : (caps_wr_ones_e ? 2'd1 : (caps_wr_alt_e ? 2'd2 : 2'd3)));
    end
  end
`endif

endmodule : dtp_debug_tdr_fcov
