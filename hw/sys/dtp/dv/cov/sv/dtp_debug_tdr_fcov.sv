// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Debug-TDR functional coverage (cg_tmp, cg_ic_reset, cg_debug_control,
// cg_clock_stop, cg_caps_tdr).
//
// One instance in the shared tb_top serves both flows. The TDR bins derive
// from the flattened TDR outputs, the committed-instruction decode, and the
// serial TDI/TDO streams of each DR scan; the TMP unit, the IC_RESET hold
// bit, and the DEBUG_CONTROL clock stop come through hierarchical
// references. A scan is sampled at the TCK rising edge that leaves
// Update-DR or Update-IR: the TDRs and the instruction register update on
// the falling edge inside that state, so the new value is already visible
// and no later TCK edge is needed. A value read from TDO counts only when
// the PTAP 3DCR select was clear at Capture-DR, because the STAP chain
// replaces the TDR output while it is set.
//
// The TAP reset is TRST AND power-on reset, as the PTAP combines them. The
// state a reset clears is judged against a copy taken at the last TCK edge
// before it, so a reset applied while TCK is idle is judged too.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables.

`include "ocah_fcov_macros.svh"

module dtp_debug_tdr_fcov (
  input wire        tck_i,
  input wire        tdi_i,
  input wire        tdo_i,
  input wire        tap_rst_ni,
  input wire        clk_i,
  input wire        rst_ni,
  input wire [15:0] tap_state_i,
  input wire [63:0] inst_decoded_i,
  input wire        ptap_stap_select_i,  // PTAP 3DCR select: the STAP chain drives TDO

  // Flattened TDR outputs (TCK domain)
  input wire        ic_reset_smc_ovrd_i,
  input wire        ic_reset_smc_ctrl_n_i,
  input wire        ic_reset_sep_ovrd_i,
  input wire        ic_reset_sep_ctrl_n_i,
  input wire        ic_reset_ext_ovrd_i,
  input wire        ic_reset_ext_ctrl_n_i,
  input wire        boot_stall_ovrd_i,
  input wire        boot_stall_i,
  input wire        cla_clock_stop_en_i,
  input wire        chrst_n_i,           // TMP conditional reset on the boundary-scan control

  // Clock-stop aggregation (clk_i domain)
  input wire        stop_clks_i,
  input wire [8:0]  clk_stop_req_i,

  // Hierarchical references
  input wire        tmp_state_i,         // 0 = persistence off, 1 = persistence on
  input wire        tmp_escape_arm_i,    // TMP_STATUS bit 0, the BYPASS escape arm
  input wire        tmp_escape_cond_i,   // TMP unit BYPASS escape condition
  input wire        ic_reset_hold_i,     // IC_RESET reset_hold
  input wire        jtag_clock_stop_i    // DEBUG_CONTROL jtag_clock_stop
);

  // ------------------------------------------------------------------
  // Decode masks (jtag_inst_reg_pkg one-hot bit positions) and TDR
  // lengths at the bench configuration.
  // ------------------------------------------------------------------
  localparam logic [63:0] BypassInstr = (64'h1 << 6'h00) | (64'h1 << 6'h3F);
  localparam logic [63:0] IdcodeInstr = 64'h1 << 6'h01;
  localparam logic [63:0] ClampHoldInstr = 64'h1 << 6'h0A;
  localparam logic [63:0] ClampReleaseInstr = 64'h1 << 6'h0B;
  localparam logic [63:0] TmpStatusTdr = 64'h1 << 6'h0C;
  localparam logic [63:0] IcResetTdr = 64'h1 << 6'h0D;
  localparam logic [63:0] DebugControlTdr = 64'h1 << 6'h18;
  localparam logic [63:0] JtagCapsTdr = 64'h1 << 6'h19;
  localparam logic [63:0] SmcOtpCapsTdr = 64'h1 << 6'h1B;
  localparam logic [63:0] SepOtpCapsTdr = 64'h1 << 6'h21;
  localparam logic [63:0] SmcCapsTdr = 64'h1 << 6'h27;
  localparam logic [63:0] AnyCapsTdr = JtagCapsTdr | SmcOtpCapsTdr | SepOtpCapsTdr | SmcCapsTdr;
  localparam logic [6:0] TmpStatusLen = 7'd2;
  localparam logic [6:0] IcResetLen = 7'd7;
  localparam logic [6:0] DebugControlLen = 7'd5;
  localparam logic [6:0] JtagCapsLen = 7'd60;
  localparam logic [6:0] Jtag2AxiCapsLen = 7'd14;

  // Sample events and classes. Each class the covergroups list under
  // illegal_bins is a design failure.
  localparam logic [2:0] TmpEvRead = 3'd0;
  localparam logic [2:0] TmpEvChange = 3'd1;
  localparam logic [2:0] TmpEvBypass = 3'd2;
  localparam logic [2:0] TmpEvTlr = 3'd3;
  localparam logic [2:0] TmpEvSysReset = 3'd4;
  localparam logic [2:0] TmpChgHoldOn = 3'd0;
  localparam logic [2:0] TmpChgReleaseOff = 3'd1;
  localparam logic [2:0] TmpChgEscapeOff = 3'd2;
  localparam logic [2:0] TmpChgTapResetOff = 3'd3;
  localparam logic [2:0] TmpChgUncausedOn = 3'd4;
  localparam logic [2:0] TmpChgUncausedOff = 3'd5;
  localparam logic [2:0] TmpChgTapResetKept = 3'd6;
  localparam logic [2:0] IcTlrPreserve = 3'd0;
  localparam logic [2:0] IcTlrRestore = 3'd1;
  localparam logic [2:0] IcTapResetRestore = 3'd2;
  localparam logic [2:0] IcTlrLost = 3'd3;
  localparam logic [2:0] IcTlrKept = 3'd4;
  localparam logic [2:0] IcTlrCorrupt = 3'd5;
  localparam logic [2:0] IcTapResetKept = 3'd6;
  localparam logic [1:0] DbgTlrCleared = 2'd0;
  localparam logic [1:0] DbgTapResetCleared = 2'd1;
  localparam logic [1:0] DbgTlrKept = 2'd2;
  localparam logic [1:0] DbgTapResetKept = 2'd3;
  localparam logic [1:0] ReadbackNone = 2'd0;
  localparam logic [1:0] ReadbackOne = 2'd1;
  localparam logic [1:0] ReadbackMulti = 2'd2;
  localparam logic [1:0] ReadbackRace = 2'd3;
  localparam logic [3:0] ReqNone = 4'd9;
  localparam logic [3:0] ReqMulti = 4'd10;

  // ------------------------------------------------------------------
  // Common scan decode, TAP-reset tracking, and the per-scan serial
  // accumulators.
  // ------------------------------------------------------------------
  wire in_reset = (tap_rst_ni !== 1'b1);
  logic [15:0] tap_state_q;
  always_ff @(posedge tck_i) tap_state_q <= tap_state_i;
  wire [15:0] tap_state_prev = tap_state_q;
  wire dr_update = (tap_state_i == jtag_tap_pkg::UPDATE_DR) && !in_reset;
  wire ir_update = (tap_state_i == jtag_tap_pkg::UPDATE_IR) && !in_reset;
  wire in_capture_dr = (tap_state_i == jtag_tap_pkg::CAPTURE_DR) && !in_reset;
  wire in_shift_dr = (tap_state_i == jtag_tap_pkg::SHIFT_DR);

  // High from a TAP reset until the first TCK edge after its release.
  logic tap_rst_seen_q;
  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) tap_rst_seen_q <= 1'b1;
    else tap_rst_seen_q <= 1'b0;
  end
  wire tap_reset_done = tap_rst_seen_q && !in_reset;
  // TMS reaches Test-Logic-Reset only from Select-IR-Scan. The
  // Test-Logic-Reset reset applies on the falling edge after entry, so the
  // next rising edge sees its result.
  wire tlr_entered = (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET)
      && (tap_state_prev == jtag_tap_pkg::SELECT_IR_SCAN) && !in_reset && !tap_rst_seen_q;

  logic [63:0] tdi_accum_q, tdo_accum_q;
  logic [6:0] shift_count_q;
  logic tdo_direct_q;
  always_ff @(posedge tck_i) begin
    if (in_capture_dr) begin
      tdi_accum_q <= '0;
      tdo_accum_q <= '0;
      shift_count_q <= '0;
      tdo_direct_q <= !ptap_stap_select_i;
    end else if (in_shift_dr) begin
      if (shift_count_q < 7'd64) begin
        tdi_accum_q[shift_count_q[5:0]] <= tdi_i;
        tdo_accum_q[shift_count_q[5:0]] <= tdo_i;
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
  // cg_tmp — TMP_STATUS reads, persistence changes and their causes,
  // BYPASS loads under persistence, chrst_n in Test-Logic-Reset, and
  // persistence across the system reset.
  // ------------------------------------------------------------------
  wire tmp_sel = |(inst_decoded_i & TmpStatusTdr);
  logic tmp_on_cap_q, tmp_arm_cap_q;
  always_ff @(posedge tck_i) begin
    if (in_capture_dr) begin
      tmp_on_cap_q <= tmp_state_i;
      tmp_arm_cap_q <= tmp_escape_arm_i;
    end
  end
  // TMP_STATUS[1:0] = {persistence, escape arm}; bit 0 leaves TDO first.
  wire [1:0] tmp_read_value = tdo_accum_q[1:0];
  wire tmp_read = dr_update && tmp_sel && (shift_count_q >= TmpStatusLen) && tdo_direct_q;
  wire tmp_read_match = (tmp_read_value == {tmp_on_cap_q, tmp_arm_cap_q});
  wire tmp_read_zero_e = tmp_read && (tmp_read_value == 2'b00);
  wire tmp_read_armed_e = tmp_read && (tmp_read_value == 2'b01);
  wire tmp_read_persist_e = tmp_read && (tmp_read_value == 2'b10);
  wire tmp_read_persist_armed_e = tmp_read && (tmp_read_value == 2'b11);
  `OCAH_FCOV_COVER(c_tmp_read_value_zero, tmp_read_zero_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_read_value_escape_armed, tmp_read_armed_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_read_value_persistence, tmp_read_persist_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_read_value_persistence_armed, tmp_read_persist_armed_e, tck_i, in_reset)

  // Persistence before this edge (held through a TAP reset), and the
  // causes the TMP unit saw at the previous edge, where a change takes
  // effect.
  logic tmp_on_q, tmp_hold_sel_q, tmp_release_sel_q, tmp_escape_q;
  always_ff @(posedge tck_i) begin
    if (!in_reset) tmp_on_q <= tmp_state_i;
    tmp_hold_sel_q <= |(inst_decoded_i & ClampHoldInstr);
    tmp_release_sel_q <= |(inst_decoded_i & ClampReleaseInstr);
    tmp_escape_q <= tmp_escape_cond_i;
  end
  wire tmp_changed = !in_reset && !tap_rst_seen_q && (tmp_state_i != tmp_on_q);
  wire tmp_reset_judged = tap_reset_done && tmp_on_q;
  logic [2:0] tmp_change;
  always_comb begin
    if (tmp_reset_judged) tmp_change = tmp_state_i ? TmpChgTapResetKept : TmpChgTapResetOff;
    else if (tmp_state_i) tmp_change = tmp_hold_sel_q ? TmpChgHoldOn : TmpChgUncausedOn;
    else if (tmp_release_sel_q) tmp_change = TmpChgReleaseOff;
    else if (tmp_escape_q) tmp_change = TmpChgEscapeOff;
    else tmp_change = TmpChgUncausedOff;
  end
  wire tmp_change_event = tmp_changed || tmp_reset_judged;
  wire tmp_hold_on_e = tmp_change_event && (tmp_change == TmpChgHoldOn);
  wire tmp_release_off_e = tmp_change_event && (tmp_change == TmpChgReleaseOff);
  wire tmp_escape_off_e = tmp_change_event && (tmp_change == TmpChgEscapeOff);
  wire tmp_reset_off_e = tmp_change_event && (tmp_change == TmpChgTapResetOff);
  `OCAH_FCOV_COVER(c_tmp_persistence_clamp_hold_on, tmp_hold_on_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_tmp_persistence_clamp_release_off, tmp_release_off_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_tmp_persistence_bypass_escape_release, tmp_escape_off_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_tmp_persistence_reset_off, tmp_reset_off_e, tck_i, 1'b0)

  // A BYPASS load while persistence is on, judged at the next edge as
  // {escape arm at the load, persistence after it}.
  logic tmp_bypass_pending_q, tmp_bypass_armed_q;
  always_ff @(posedge tck_i) begin
    tmp_bypass_pending_q <= ir_update && |(inst_decoded_i & BypassInstr) && tmp_state_i;
    tmp_bypass_armed_q <= tmp_escape_arm_i;
  end
  wire tmp_bypass_judged = tmp_bypass_pending_q && !in_reset && !tap_rst_seen_q;
  wire [1:0] tmp_bypass_outcome = {tmp_bypass_armed_q, tmp_state_i};
  wire tmp_bypass_unarmed_e = tmp_bypass_judged && (tmp_bypass_outcome == 2'b01);
  wire tmp_bypass_armed_e = tmp_bypass_judged && (tmp_bypass_outcome == 2'b10);
  `OCAH_FCOV_COVER(c_tmp_escape_unarmed, tmp_bypass_unarmed_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_escape_armed, tmp_bypass_armed_e, tck_i, in_reset)

  // {persistence, chrst_n} in Test-Logic-Reset.
  wire [1:0] tmp_tlr_chrst = {tmp_state_i, chrst_n_i};
  wire tmp_tlr_released_e = tlr_entered && (tmp_tlr_chrst == 2'b11);
  wire tmp_tlr_asserted_e = tlr_entered && (tmp_tlr_chrst == 2'b00);
  `OCAH_FCOV_COVER(c_tmp_tlr_chrst_released, tmp_tlr_released_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_tmp_tlr_chrst_asserted, tmp_tlr_asserted_e, tck_i, in_reset)

  // Persistence on both when the system reset asserts and when it releases
  // (system-clock domain; rst_ni does not reset the TAP).
  logic sys_rst_nq, sys_tmp_on_q;
  always_ff @(posedge clk_i) begin
    sys_rst_nq <= rst_ni;
    if (sys_rst_nq && !rst_ni) sys_tmp_on_q <= tmp_state_i;
  end
  wire sys_rst_released = !sys_rst_nq && rst_ni;
  wire tmp_sys_judged = sys_rst_released && sys_tmp_on_q;
  wire tmp_sys_preserved_e = tmp_sys_judged && tmp_state_i;
  `OCAH_FCOV_COVER(c_tmp_persistence_chip_reset_preserved, tmp_sys_preserved_e, clk_i, 1'b0)

  // ------------------------------------------------------------------
  // cg_ic_reset — slice values on each IC_RESET update, the reset_hold
  // written, and the register across Test-Logic-Reset and a TAP reset.
  // Each slice is {ovrd, ctrl_n}.
  // ------------------------------------------------------------------
  localparam logic [5:0] IcDefault = 6'b01_01_01;
  wire ic_sel = |(inst_decoded_i & IcResetTdr);
  wire [1:0] ic_smc = {ic_reset_smc_ovrd_i, ic_reset_smc_ctrl_n_i};
  wire [1:0] ic_sep = {ic_reset_sep_ovrd_i, ic_reset_sep_ctrl_n_i};
  wire [1:0] ic_ext = {ic_reset_ext_ovrd_i, ic_reset_ext_ctrl_n_i};
  wire [5:0] ic_now = {ic_smc, ic_sep, ic_ext};
  wire ic_commit = dr_update && ic_sel && (shift_count_q >= IcResetLen);

  `define DTP_FCOV_IC_SLICE(__slice)                                                        \
    wire ic_``__slice``_functional_e = ic_commit && (ic_``__slice == 2'b01);              \
    wire ic_``__slice``_staged_e = ic_commit && (ic_``__slice == 2'b00);                  \
    wire ic_``__slice``_override_reset_e = ic_commit && (ic_``__slice == 2'b10);          \
    wire ic_``__slice``_override_run_e = ic_commit && (ic_``__slice == 2'b11);            \
    `OCAH_FCOV_COVER(c_ic_reset_``__slice``_functional, ic_``__slice``_functional_e, tck_i, \
                     in_reset)                                                            \
    `OCAH_FCOV_COVER(c_ic_reset_``__slice``_staged, ic_``__slice``_staged_e, tck_i, in_reset) \
    `OCAH_FCOV_COVER(c_ic_reset_``__slice``_override_reset, ic_``__slice``_override_reset_e, \
                     tck_i, in_reset)                                                     \
    `OCAH_FCOV_COVER(c_ic_reset_``__slice``_override_run, ic_``__slice``_override_run_e,  \
                     tck_i, in_reset)
  `DTP_FCOV_IC_SLICE(smc)
  `DTP_FCOV_IC_SLICE(sep)
  `DTP_FCOV_IC_SLICE(ext)
  `undef DTP_FCOV_IC_SLICE
  wire ic_hold_clear_e = ic_commit && !ic_reset_hold_i;
  wire ic_hold_set_e = ic_commit && ic_reset_hold_i;
  `OCAH_FCOV_COVER(c_ic_reset_hold_write_clear, ic_hold_clear_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_ic_reset_hold_write_set, ic_hold_set_e, tck_i, in_reset)

  // Register image {reset_hold, slices} before this edge, held through a
  // TAP reset. Test-Logic-Reset is judged on slices away from their
  // default under the reset_hold set before it; a TAP reset is judged on
  // any image away from the default.
  // ic_valid_q marks a copy taken out of reset, so the reset that starts
  // the simulation is not judged.
  logic [6:0] ic_q;
  logic ic_valid_q;
  always_ff @(posedge tck_i) begin
    if (!in_reset) begin
      ic_q <= {ic_reset_hold_i, ic_now};
      ic_valid_q <= 1'b1;
    end
  end
  wire ic_preserved = ({ic_reset_hold_i, ic_now} == ic_q);
  wire ic_restored = ({ic_reset_hold_i, ic_now} == {1'b1, IcDefault});
  wire ic_tlr_judged = tlr_entered && (ic_q[5:0] != IcDefault);
  wire ic_reset_judged = tap_reset_done && ic_valid_q && (ic_q != {1'b1, IcDefault});
  logic [2:0] ic_reset_outcome;
  always_comb begin
    if (ic_reset_judged) begin
      ic_reset_outcome = ic_restored ? IcTapResetRestore : IcTapResetKept;
    end else if (!ic_q[6]) begin
      ic_reset_outcome = ic_preserved ? IcTlrPreserve : (ic_restored ? IcTlrLost : IcTlrCorrupt);
    end else begin
      ic_reset_outcome = ic_restored ? IcTlrRestore : (ic_preserved ? IcTlrKept : IcTlrCorrupt);
    end
  end
  wire ic_reset_event = ic_tlr_judged || ic_reset_judged;
  wire ic_hold_tlr_preserve_e = ic_reset_event && (ic_reset_outcome == IcTlrPreserve);
  wire ic_hold_tlr_restore_e = ic_reset_event && (ic_reset_outcome == IcTlrRestore);
  wire ic_hold_tap_reset_restore_e = ic_reset_event && (ic_reset_outcome == IcTapResetRestore);
  `OCAH_FCOV_COVER(c_ic_reset_hold_tlr_preserve, ic_hold_tlr_preserve_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_ic_reset_hold_tlr_restore, ic_hold_tlr_restore_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_ic_reset_hold_tap_reset_restore, ic_hold_tap_reset_restore_e, tck_i, 1'b0)

  // ------------------------------------------------------------------
  // cg_debug_control — DEBUG_CONTROL fields on each update, the
  // cla_clock_stop readback against the request lines at Capture-DR, and
  // the fields across Test-Logic-Reset and a TAP reset.
  // ------------------------------------------------------------------
  wire dbgctl_sel = |(inst_decoded_i & DebugControlTdr);
  // {jtag_clock_stop, cla_clock_stop_en, boot_stall_ovrd, boot_stall}.
  wire [3:0] dbgctl_now = {jtag_clock_stop_i, cla_clock_stop_en_i, boot_stall_ovrd_i, boot_stall_i};
  wire dbgctl_commit = dr_update && dbgctl_sel && (shift_count_q >= DebugControlLen);
  wire boot_00_e = dbgctl_commit && (dbgctl_now[1:0] == 2'b00);
  wire boot_01_e = dbgctl_commit && (dbgctl_now[1:0] == 2'b01);
  wire boot_10_e = dbgctl_commit && (dbgctl_now[1:0] == 2'b10);
  wire boot_11_e = dbgctl_commit && (dbgctl_now[1:0] == 2'b11);
  `OCAH_FCOV_COVER(c_boot_stall_ovrd0_stall0, boot_00_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_ovrd0_stall1, boot_01_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_ovrd1_stall0, boot_10_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_ovrd1_stall1, boot_11_e, tck_i, in_reset)
  wire boot_ovrd_commit = dbgctl_commit && boot_stall_ovrd_i;
  wire boot_standalone_e = boot_ovrd_commit && (dbgctl_now[3:2] == 2'b00);
  wire boot_with_cla_en_e = boot_ovrd_commit && (dbgctl_now[3:2] == 2'b01);
  wire boot_with_jtag_stop_e = boot_ovrd_commit && (dbgctl_now[3:2] == 2'b10);
  wire boot_with_both_e = boot_ovrd_commit && (dbgctl_now[3:2] == 2'b11);
  `OCAH_FCOV_COVER(c_boot_stall_standalone, boot_standalone_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_with_cla_en, boot_with_cla_en_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_with_jtag_stop, boot_with_jtag_stop_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_boot_stall_with_both, boot_with_both_e, tck_i, in_reset)
  wire jtag_stop_on_e = dbgctl_commit && jtag_clock_stop_i;
  wire jtag_stop_off_e = dbgctl_commit && !jtag_clock_stop_i;
  wire cla_en_on_e = dbgctl_commit && cla_clock_stop_en_i;
  wire cla_en_off_e = dbgctl_commit && !cla_clock_stop_en_i;
  `OCAH_FCOV_COVER(c_jtag_clock_stop_asserted, jtag_stop_on_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag_clock_stop_deasserted, jtag_stop_off_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_clock_stop_en_enabled, cla_en_on_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_clock_stop_en_disabled, cla_en_off_e, tck_i, in_reset)

  // Bit 4 captures the request OR through a two-flop TCK synchronizer, so a
  // request change within two TCK edges of Capture-DR reads either way and
  // counts in no readback bin.
  wire [3:0] req_count = 4'($countones(clk_stop_req_i));
  logic [1:0] dbg_req_cap_q;
  logic [1:0] dbg_stop_fields_cap_q;
  always_ff @(posedge tck_i) begin
    if (in_capture_dr) begin
      dbg_req_cap_q <= (req_count == 4'd0) ? ReadbackNone
          : ((req_count == 4'd1) ? ReadbackOne : ReadbackMulti);
      dbg_stop_fields_cap_q <= {jtag_clock_stop_i, cla_clock_stop_en_i};
    end
  end
  wire dbg_readback_bit = tdo_accum_q[4];
  wire dbg_readback_valid = dbgctl_commit && tdo_direct_q;
  wire [1:0] dbg_readback = (dbg_readback_bit == (dbg_req_cap_q != ReadbackNone))
      ? dbg_req_cap_q : ReadbackRace;
  wire cla_readback_none_e = dbg_readback_valid && (dbg_readback == ReadbackNone);
  wire cla_readback_one_e = dbg_readback_valid && (dbg_readback == ReadbackOne);
  wire cla_readback_multi_e = dbg_readback_valid && (dbg_readback == ReadbackMulti);
  `OCAH_FCOV_COVER(c_cla_readback_no_request, cla_readback_none_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_readback_one_request, cla_readback_one_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_readback_multiple_requests, cla_readback_multi_e, tck_i, in_reset)

  // Fields before this edge, held through a TAP reset. Only nonzero
  // fields are judged.
  logic [3:0] dbgctl_q;
  always_ff @(posedge tck_i) begin
    if (!in_reset) dbgctl_q <= dbgctl_now;
  end
  wire dbgctl_cleared = (dbgctl_now == 4'h0);
  wire dbgctl_tlr_judged = tlr_entered && (dbgctl_q != 4'h0);
  wire dbgctl_reset_judged = tap_reset_done && (dbgctl_q != 4'h0);
  wire [1:0] dbgctl_reset_outcome = dbgctl_reset_judged
      ? (dbgctl_cleared ? DbgTapResetCleared : DbgTapResetKept)
      : (dbgctl_cleared ? DbgTlrCleared : DbgTlrKept);
  wire dbgctl_reset_event = dbgctl_tlr_judged || dbgctl_reset_judged;
  wire dbgctl_tlr_cleared_e = dbgctl_reset_event && (dbgctl_reset_outcome == DbgTlrCleared);
  wire dbgctl_tap_reset_cleared_e =
      dbgctl_reset_event && (dbgctl_reset_outcome == DbgTapResetCleared);
  `OCAH_FCOV_COVER(c_debug_control_tlr_cleared, dbgctl_tlr_cleared_e, tck_i, 1'b0)
  `OCAH_FCOV_COVER(c_debug_control_tap_reset_cleared, dbgctl_tap_reset_cleared_e, tck_i, 1'b0)

  // ------------------------------------------------------------------
  // cg_clock_stop — stop_clks_o against the sources that produced it.
  // stop_clks_o follows the OR of jtag_clock_stop and the request lines
  // three clk_i edges later, or four when the synchronizer's CDC delay
  // model holds an input change back an edge. A source combination held
  // for two clk_i edges is judged four edges after it is first sampled,
  // where stop_clks_o shows it at either latency. cla_clock_stop_en rides
  // along so each DEBUG_CONTROL combination gives its own sample.
  // ------------------------------------------------------------------
  wire clk_in_reset = (rst_ni !== 1'b1);
  logic [10:0] stop_src_d1, stop_src_d2, stop_src_d3, stop_src_d4, stop_src_d5;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      stop_src_d1 <= '0;
      stop_src_d2 <= '0;
      stop_src_d3 <= '0;
      stop_src_d4 <= '0;
      stop_src_d5 <= '0;
    end else begin
      stop_src_d1 <= {cla_clock_stop_en_i, jtag_clock_stop_i, clk_stop_req_i};
      stop_src_d2 <= stop_src_d1;
      stop_src_d3 <= stop_src_d2;
      stop_src_d4 <= stop_src_d3;
      stop_src_d5 <= stop_src_d4;
    end
  end
  wire stop_sample = !clk_in_reset && (stop_src_d3 == stop_src_d4) && (stop_src_d4 != stop_src_d5);
  wire [8:0] stop_req = stop_src_d4[8:0];
  wire stop_jtag = stop_src_d4[9];
  wire stop_cla_en = stop_src_d4[10];
  // Request source: the line index of a single request, ReqNone, or
  // ReqMulti.
  logic [3:0] stop_req_source;
  always_comb begin
    stop_req_source = (stop_req == '0) ? ReqNone : ReqMulti;
    for (int unsigned i = 0; i < 9; i++) begin
      if (stop_req == (9'h1 << i)) stop_req_source = 4'(i);
    end
  end
  `define DTP_FCOV_REQ_LINE(__label, __idx)                                    \
    wire __label``_e = stop_sample && (stop_req_source == 4'(__idx));          \
    `OCAH_FCOV_COVER(__label, __label``_e, clk_i, clk_in_reset)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_0, 0)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_1, 1)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_2, 2)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_3, 3)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_4, 4)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_5, 5)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_6, 6)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_7, 7)
  `DTP_FCOV_REQ_LINE(c_clk_stop_req_bit_8, 8)
  `undef DTP_FCOV_REQ_LINE
  wire req_none_e = stop_sample && (stop_req_source == ReqNone);
  wire req_multi_e = stop_sample && (stop_req_source == ReqMulti);
  `OCAH_FCOV_COVER(c_clk_stop_req_none, req_none_e, clk_i, clk_in_reset)
  `OCAH_FCOV_COVER(c_clk_stop_req_multi_mask, req_multi_e, clk_i, clk_in_reset)

  wire stop_any_req = (stop_req != '0);
  wire stop_out_jtag_only_e = stop_sample && stop_clks_i && stop_jtag && !stop_any_req;
  wire stop_out_cla_only_e = stop_sample && stop_clks_i && !stop_jtag && stop_any_req;
  wire stop_out_combined_e = stop_sample && stop_clks_i && stop_jtag && stop_any_req;
  wire stop_out_released_e = stop_sample && !stop_clks_i && !stop_jtag && !stop_any_req;
  `OCAH_FCOV_COVER(c_clock_stop_output_jtag_only, stop_out_jtag_only_e, clk_i, clk_in_reset)
  `OCAH_FCOV_COVER(c_clock_stop_output_cla_only, stop_out_cla_only_e, clk_i, clk_in_reset)
  `OCAH_FCOV_COVER(c_clock_stop_output_combined, stop_out_combined_e, clk_i, clk_in_reset)
  `OCAH_FCOV_COVER(c_clock_stop_output_released, stop_out_released_e, clk_i, clk_in_reset)

  // ------------------------------------------------------------------
  // cg_caps_tdr — full-length capability-TDR scans: the register, the
  // pattern shifted in, the instruction committed before it, and the
  // value read against that register's previous direct read.
  // ------------------------------------------------------------------
  wire caps_jtag_sel = |(inst_decoded_i & JtagCapsTdr);
  wire caps_smc_sel = |(inst_decoded_i & SmcCapsTdr);
  wire caps_smc_otp_sel = |(inst_decoded_i & SmcOtpCapsTdr);
  wire caps_any_sel = |(inst_decoded_i & AnyCapsTdr);
  wire [1:0] caps_reg = caps_jtag_sel ? 2'd0
      : (caps_smc_sel ? 2'd1 : (caps_smc_otp_sel ? 2'd2 : 2'd3));
  wire [6:0] caps_len = caps_jtag_sel ? JtagCapsLen : Jtag2AxiCapsLen;
  wire caps_commit = dr_update && caps_any_sel && (shift_count_q >= caps_len);

  // Two-stage committed-instruction history: at an IR update the decode
  // already shows the new instruction, so the instruction before the
  // current one is the previous update's class.
  logic cur_instr_idcode_q, cur_instr_bypass_q;
  logic prev_instr_idcode_q, prev_instr_bypass_q;
  always_ff @(posedge tck_i) begin
    if (ir_update) begin
      prev_instr_idcode_q <= cur_instr_idcode_q;
      prev_instr_bypass_q <= cur_instr_bypass_q;
      cur_instr_idcode_q <= |(inst_decoded_i & IdcodeInstr);
      cur_instr_bypass_q <= |(inst_decoded_i & BypassInstr);
    end
  end

  // The previous direct full read of each register.
  logic [63:0] caps_last_q[4];
  logic [3:0] caps_seen_q;
  wire [63:0] caps_len_mask = (64'h1 << caps_len) - 64'h1;
  wire [63:0] caps_value = tdo_accum_q & caps_len_mask;
  wire caps_read_direct = caps_commit && tdo_direct_q;
  always_ff @(posedge tck_i) begin
    if (caps_read_direct) begin
      caps_last_q[caps_reg] <= caps_value;
      caps_seen_q[caps_reg] <= 1'b1;
    end
  end
  wire caps_judged = caps_read_direct && caps_seen_q[caps_reg];
  wire caps_stable = (caps_value == caps_last_q[caps_reg]);

  wire caps_read_jtag_e = caps_commit && (caps_reg == 2'd0);
  wire caps_read_smc_e = caps_commit && (caps_reg == 2'd1);
  wire caps_read_smc_otp_e = caps_commit && (caps_reg == 2'd2);
  wire caps_read_sep_otp_e = caps_commit && (caps_reg == 2'd3);
  wire caps_stable_e = caps_judged && caps_stable;
  wire caps_after_idcode_e = caps_commit && prev_instr_idcode_q;
  wire caps_after_bypass_e = caps_commit && prev_instr_bypass_q;
  `OCAH_FCOV_COVER(c_caps_read_jtag_caps, caps_read_jtag_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_smc_jtag2axi_caps, caps_read_smc_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_smc_otp_jtag2axi_caps, caps_read_smc_otp_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_sep_otp_jtag2axi_caps, caps_read_sep_otp_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_repeated_read, caps_stable_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_after_idcode, caps_after_idcode_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_read_after_bypass, caps_after_bypass_e, tck_i, in_reset)

  wire [63:0] alt_a = 64'hAAAA_AAAA_AAAA_AAAA & shifted_mask;
  wire [63:0] alt_5 = 64'h5555_5555_5555_5555 & shifted_mask;
  wire caps_pat_zero = (shifted_bits == '0);
  wire caps_pat_ones = (shifted_bits == shifted_mask);
  wire caps_pat_alt = (shifted_bits == alt_a) || (shifted_bits == alt_5);
  wire [1:0] caps_pattern = caps_pat_zero ? 2'd0
      : (caps_pat_ones ? 2'd1 : (caps_pat_alt ? 2'd2 : 2'd3));
  wire caps_wr_zero_e = caps_commit && (caps_pattern == 2'd0);
  wire caps_wr_ones_e = caps_commit && (caps_pattern == 2'd1);
  wire caps_wr_alt_e = caps_commit && (caps_pattern == 2'd2);
  wire caps_wr_mixed_e = caps_commit && (caps_pattern == 2'd3);
  `OCAH_FCOV_COVER(c_caps_write_attempt_all_zero, caps_wr_zero_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_write_attempt_all_one, caps_wr_ones_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_write_attempt_alternating, caps_wr_alt_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_caps_write_attempt_random, caps_wr_mixed_e, tck_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups.
  // ------------------------------------------------------------------
  covergroup cg_tmp with function sample (
      logic [2:0] ev,
      logic [1:0] read_value,
      logic read_match,
      logic [2:0] change,
      logic [1:0] bypass_outcome,
      logic [1:0] tlr_chrst,
      logic sys_preserved
  );
    option.per_instance = 1;
    // TMP_STATUS[1:0] = {persistence, escape arm}.
    cp_read_value: coverpoint read_value iff (ev == TmpEvRead) {
      bins zero = {2'b00};
      bins escape_armed = {2'b01};
      bins persistence = {2'b10};
      bins persistence_armed = {2'b11};
    }
    // Capture-DR loads the persistence state and the escape arm.
    cp_read_match: coverpoint read_match iff (ev == TmpEvRead) {
      bins match = {1'b1}; illegal_bins mismatch = {1'b0};
    }
    // Persistence moves only on CLAMP_HOLD, CLAMP_RELEASE, an armed BYPASS
    // load, or a TAP reset.
    cp_change: coverpoint change iff (ev == TmpEvChange) {
      bins clamp_hold_on = {TmpChgHoldOn};
      bins clamp_release_off = {TmpChgReleaseOff};
      bins bypass_escape_off = {TmpChgEscapeOff};
      bins tap_reset_off = {TmpChgTapResetOff};
      illegal_bins uncaused = {TmpChgUncausedOn, TmpChgUncausedOff, TmpChgTapResetKept};
    }
    // {escape arm, persistence after the load}: only an armed load escapes.
    cp_bypass: coverpoint bypass_outcome iff (ev == TmpEvBypass) {
      bins unarmed_held = {2'b01};
      bins armed_escaped = {2'b10};
      illegal_bins escape_mismatch = {2'b00, 2'b11};
    }
    // {persistence, chrst_n} in Test-Logic-Reset.
    cp_tlr: coverpoint tlr_chrst iff (ev == TmpEvTlr) {
      bins persistence_on_released = {2'b11};
      bins persistence_off_asserted = {2'b00};
      illegal_bins chrst_mismatch = {2'b01, 2'b10};
    }
    cp_sys_reset: coverpoint sys_preserved iff (ev == TmpEvSysReset) {
      bins persistence_preserved = {1'b1};
    }
  endgroup

  covergroup cg_ic_reset with function sample (
      logic commit,
      logic [1:0] smc,
      logic [1:0] sep,
      logic [1:0] ext,
      logic hold,
      logic [2:0] reset_outcome
  );
    option.per_instance = 1;
    // Each slice is {ovrd, ctrl_n}.
    cp_smc: coverpoint smc iff (commit) {
      bins functional = {2'b01};
      bins staged = {2'b00};
      bins override_reset = {2'b10};
      bins override_run = {2'b11};
    }
    cp_sep: coverpoint sep iff (commit) {
      bins functional = {2'b01};
      bins staged = {2'b00};
      bins override_reset = {2'b10};
      bins override_run = {2'b11};
    }
    cp_ext: coverpoint ext iff (commit) {
      bins functional = {2'b01};
      bins staged = {2'b00};
      bins override_reset = {2'b10};
      bins override_run = {2'b11};
    }
    cp_hold: coverpoint hold iff (commit) {bins hold_clear = {1'b0}; bins hold_set = {1'b1};}
    // Test-Logic-Reset keeps the enable/control bits while reset_hold is 0
    // and restores them while it is 1; a TAP reset always restores them.
    cp_reset: coverpoint reset_outcome iff (!commit) {
      bins tlr_preserve = {IcTlrPreserve};
      bins tlr_restore = {IcTlrRestore};
      bins tap_reset_restore = {IcTapResetRestore};
      illegal_bins hold_violated = {IcTlrLost, IcTlrKept, IcTlrCorrupt, IcTapResetKept};
    }
  endgroup

  covergroup cg_debug_control with function sample (
      logic commit,
      logic [1:0] boot,
      logic jtag_stop,
      logic cla_en,
      logic readback_valid,
      logic [1:0] readback,
      logic [1:0] capture_stop_fields,
      logic [1:0] reset_outcome
  );
    option.per_instance = 1;
    // {boot_stall_ovrd, boot_stall}.
    cp_boot: coverpoint boot iff (commit) {
      bins ovrd0_stall0 = {2'b00};
      bins ovrd0_stall1 = {2'b01};
      bins ovrd1_stall0 = {2'b10};
      bins ovrd1_stall1 = {2'b11};
    }
    cp_jtag_stop: coverpoint jtag_stop iff (commit) {bins off = {1'b0}; bins on = {1'b1};}
    cp_cla_en: coverpoint cla_en iff (commit) {bins off = {1'b0}; bins on = {1'b1};}
    x_boot_clock_stop: cross cp_boot, cp_jtag_stop, cp_cla_en;
    cp_readback: coverpoint readback iff (readback_valid) {
      bins no_request = {ReadbackNone};
      bins one_request = {ReadbackOne};
      bins multiple_requests = {ReadbackMulti};
    }
    // {jtag_clock_stop, cla_clock_stop_en} while bit 4 was captured.
    cp_capture_jtag_stop: coverpoint capture_stop_fields[1] iff (readback_valid) {
      bins off = {1'b0}; bins on = {1'b1};
    }
    cp_capture_cla_en: coverpoint capture_stop_fields[0] iff (readback_valid) {
      bins off = {1'b0}; bins on = {1'b1};
    }
    x_readback: cross cp_readback, cp_capture_jtag_stop, cp_capture_cla_en;
    // Test-Logic-Reset and a TAP reset clear every field.
    cp_reset: coverpoint reset_outcome iff (!commit) {
      bins tlr_cleared = {DbgTlrCleared};
      bins tap_reset_cleared = {DbgTapResetCleared};
      illegal_bins kept = {DbgTlrKept, DbgTapResetKept};
    }
  endgroup

  covergroup cg_clock_stop with function sample (
      logic [3:0] req_source, logic jtag_stop, logic cla_en, logic stop_clks
  );
    option.per_instance = 1;
    cp_req_source: coverpoint req_source {
      bins line_0 = {4'd0};
      bins line_1 = {4'd1};
      bins line_2 = {4'd2};
      bins line_3 = {4'd3};
      bins line_4 = {4'd4};
      bins line_5 = {4'd5};
      bins line_6 = {4'd6};
      bins line_7 = {4'd7};
      bins line_8 = {4'd8};
      bins none = {ReqNone};
      bins multi = {ReqMulti};
    }
    cp_jtag_stop: coverpoint jtag_stop {bins off = {1'b0}; bins on = {1'b1};}
    cp_cla_en: coverpoint cla_en {bins off = {1'b0}; bins on = {1'b1};}
    cp_stop_clks: coverpoint stop_clks {bins running = {1'b0}; bins stopped = {1'b1};}
    // stop_clks_o is the OR of jtag_clock_stop and every request line;
    // cla_clock_stop_en takes no part in it.
    x_aggregation: cross cp_req_source, cp_jtag_stop, cp_cla_en, cp_stop_clks{
      illegal_bins stopped_without_source =
          binsof (cp_req_source.none) && binsof (cp_jtag_stop.off) && binsof (cp_stop_clks.stopped);
      illegal_bins running_with_source = binsof (cp_stop_clks.running)
          && (binsof (cp_jtag_stop.on) || !binsof (cp_req_source.none));
    }
  endgroup

  covergroup cg_caps_tdr with function sample (
      logic [1:0] which, logic [1:0] pattern, logic [1:0] after, logic judged, logic stable
  );
    option.per_instance = 1;
    cp_register: coverpoint which {
      bins jtag_caps = {2'd0};
      bins smc_caps = {2'd1};
      bins smc_otp_caps = {2'd2};
      bins sep_otp_caps = {2'd3};
    }
    cp_pattern: coverpoint pattern {
      bins all_zero = {2'd0}; bins all_one = {2'd1}; bins alternating = {2'd2}; bins mixed = {2'd3};
    }
    // {IDCODE, BYPASS}: the instruction committed before the capability
    // instruction.
    cp_after: coverpoint after {
      bins after_idcode = {2'b10}; bins after_bypass = {2'b01};
    }
    // Capability values are elaboration-time constants.
    cp_stability: coverpoint stable iff (judged) {
      bins stable = {1'b1}; illegal_bins changed = {1'b0};
    }
    x_register_pattern: cross cp_register, cp_pattern;
    x_register_after: cross cp_register, cp_after;
    x_register_stability: cross cp_register, cp_stability;
  endgroup

  cg_tmp u_cg_tmp = new();
  cg_ic_reset u_cg_ic_reset = new();
  cg_debug_control u_cg_debug_control = new();
  cg_clock_stop u_cg_clock_stop = new();
  cg_caps_tdr u_cg_caps_tdr = new();

  always_ff @(posedge tck_i) begin
    if (tmp_read) begin
      u_cg_tmp.sample(TmpEvRead, tmp_read_value, tmp_read_match, '0, '0, '0, 1'b0);
    end
    if (tmp_change_event) begin
      u_cg_tmp.sample(TmpEvChange, '0, 1'b1, tmp_change, '0, '0, 1'b0);
    end
    if (tmp_bypass_judged) begin
      u_cg_tmp.sample(TmpEvBypass, '0, 1'b1, '0, tmp_bypass_outcome, '0, 1'b0);
    end
    if (tlr_entered) begin
      u_cg_tmp.sample(TmpEvTlr, '0, 1'b1, '0, '0, tmp_tlr_chrst, 1'b0);
    end
    if (ic_commit) begin
      u_cg_ic_reset.sample(1'b1, ic_smc, ic_sep, ic_ext, ic_reset_hold_i, '0);
    end
    if (ic_reset_event) begin
      u_cg_ic_reset.sample(1'b0, '0, '0, '0, ic_reset_hold_i, ic_reset_outcome);
    end
    if (dbgctl_commit) begin
      u_cg_debug_control.sample(1'b1, dbgctl_now[1:0], jtag_clock_stop_i, cla_clock_stop_en_i,
                                dbg_readback_valid, dbg_readback, dbg_stop_fields_cap_q, '0);
    end
    if (dbgctl_reset_event) begin
      u_cg_debug_control.sample(1'b0, '0, 1'b0, 1'b0, 1'b0, '0, '0, dbgctl_reset_outcome);
    end
    if (caps_commit) begin
      u_cg_caps_tdr.sample(caps_reg, caps_pattern, {prev_instr_idcode_q, prev_instr_bypass_q},
                           caps_judged, caps_stable);
    end
  end

  always_ff @(posedge clk_i) begin
    if (tmp_sys_judged) begin
      u_cg_tmp.sample(TmpEvSysReset, '0, 1'b1, '0, '0, '0, tmp_state_i);
    end
    if (stop_sample) begin
      u_cg_clock_stop.sample(stop_req_source, stop_jtag, stop_cla_en, stop_clks_i);
    end
  end
`endif

endmodule : dtp_debug_tdr_fcov
