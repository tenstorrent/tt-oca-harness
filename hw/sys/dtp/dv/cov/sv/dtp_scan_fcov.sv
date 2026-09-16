// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scan-network functional coverage (stap_3dcr_cg, ijtag_sib_cg) plus the
// SV cross-check mirror of the dbg_disable_cg gating conditions. The
// checker-gated 22-cell debug-disable contract itself stays with the Python
// ledger (DtpDbgDisableFcov); the mirror here only records that each field
// value was exercised.
//
// One instance in the shared tb_top serves both flows. The iJTAG chain
// controls and STAP legs are flattened DUT outputs; each STAP's stored 3DCR
// state (select / TMS hold / config hold, pre- and post-security-gating)
// comes through hierarchical references — `stap_sel_int && !stap_sel` is the
// security gate acting.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module dtp_scan_fcov (
  input wire        tck_i,
  input wire        trst_ni,
  input wire [15:0] tap_state_i,
  input wire [63:0] inst_decoded_i,
  input wire sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_i,

  // iJTAG chain controls (flattened DUT outputs)
  input wire dft_secure_select_i,
  input wire dft_secure_shift_en_i,
  input wire dft_select_i,
  input wire dft_shift_en_i,
  input wire dfd_select_i,
  input wire dfd_shift_en_i,

  // STAP legs (flattened DUT outputs)
  input wire stap_io_tdo_oen_i,
  input wire stap_smc_tdo_oen_i,
  input wire stap_sep_tdo_oen_i,
  input wire stap_extra_tdo_oen_i,

  // STAP stored 3DCR state (hierarchical references)
  input wire stap_io_sel_i,
  input wire stap_io_sel_int_i,
  input wire stap_io_tms_hold_i,
  input wire stap_io_config_hold_i,
  input wire stap_smc_sel_i,
  input wire stap_smc_sel_int_i,
  input wire stap_smc_tms_hold_i,
  input wire stap_smc_config_hold_i,
  input wire stap_sep_sel_i,
  input wire stap_sep_sel_int_i,
  input wire stap_sep_tms_hold_i,
  input wire stap_sep_config_hold_i,
  input wire stap_extra_sel_i,
  input wire stap_extra_sel_int_i,
  input wire stap_extra_tms_hold_i,
  input wire stap_extra_config_hold_i
);

  localparam logic [63:0] SelectIjtagInstr = 64'h1 << 6'h1A;
  localparam logic [63:0] Tap3dcrInstr = 64'h1 << 6'h0E;

  // ------------------------------------------------------------------
  // Common scan decode.
  // ------------------------------------------------------------------
  wire in_reset = (trst_ni !== 1'b1);
  logic [15:0] tap_state_q;
  always_ff @(posedge tck_i) tap_state_q <= tap_state_i;
  wire [15:0] tap_state_prev = tap_state_q;
  wire dr_committed = (tap_state_prev == jtag_tap_pkg::UPDATE_DR) && !in_reset;
  wire in_capture_dr = (tap_state_i == jtag_tap_pkg::CAPTURE_DR);
  wire ijtag_sel = |(inst_decoded_i & SelectIjtagInstr);
  wire tap_3dcr_sel = |(inst_decoded_i & Tap3dcrInstr);
  wire ijtag_committed = dr_committed && ijtag_sel;
  wire tap_3dcr_committed = dr_committed && tap_3dcr_sel;

  // ------------------------------------------------------------------
  // ijtag_sib_cg — SIB pattern per completed iJTAG scan, instrument
  // access, and per-field security gating. A chain's select going active
  // during the scan means its SIB is open.
  // ------------------------------------------------------------------
  logic sib_dfd_seen_q, sib_dfts_seen_q, sib_dftn_seen_q;
  always_ff @(posedge tck_i) begin
    if (in_capture_dr) begin
      sib_dfd_seen_q <= 1'b0;
      sib_dfts_seen_q <= 1'b0;
      sib_dftn_seen_q <= 1'b0;
    end else begin
      if (dfd_select_i) sib_dfd_seen_q <= 1'b1;
      if (dft_secure_select_i) sib_dfts_seen_q <= 1'b1;
      if (dft_select_i) sib_dftn_seen_q <= 1'b1;
    end
  end

  `define DTP_SIB_PATTERN(__label, __dfd, __dfts, __dftn)                          \
    wire __label``_e = ijtag_committed && (sib_dfd_seen_q == (__dfd))        \
        && (sib_dfts_seen_q == (__dfts)) && (sib_dftn_seen_q == (__dftn));         \
    `OCAH_FCOV_COVER(__label, __label``_e, tck_i, in_reset)

  `DTP_SIB_PATTERN(c_sib_pattern_dfd0_dfts0_dftn0, 1'b0, 1'b0, 1'b0)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd0_dfts0_dftn1, 1'b0, 1'b0, 1'b1)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd0_dfts1_dftn0, 1'b0, 1'b1, 1'b0)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd0_dfts1_dftn1, 1'b0, 1'b1, 1'b1)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd1_dfts0_dftn0, 1'b1, 1'b0, 1'b0)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd1_dfts0_dftn1, 1'b1, 1'b0, 1'b1)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd1_dfts1_dftn0, 1'b1, 1'b1, 1'b0)
  `DTP_SIB_PATTERN(c_sib_pattern_dfd1_dfts1_dftn1, 1'b1, 1'b1, 1'b1)
  `undef DTP_SIB_PATTERN

  wire instr_access_dfd_e = dfd_select_i && dfd_shift_en_i && !in_reset;
  wire instr_access_dfts_e = dft_secure_select_i && dft_secure_shift_en_i
      && !in_reset;
  wire instr_access_dftn_e = dft_select_i && dft_shift_en_i && !in_reset;
  `OCAH_FCOV_COVER(c_instrument_access_dfd, instr_access_dfd_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_instrument_access_dft_secure, instr_access_dfts_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_instrument_access_dft_nonsecure, instr_access_dftn_e, tck_i, in_reset)

  wire sib_enabled_dfd_e = dfd_select_i && !dbg_disable_i.dfd;
  wire sib_enabled_dfts_e = dft_secure_select_i && !dbg_disable_i.dft_secure;
  wire sib_enabled_dftn_e = dft_select_i && !dbg_disable_i.dft_nonsecure;
  wire sib_gated_dfd_e = ijtag_committed && dbg_disable_i.dfd && !sib_dfd_seen_q;
  wire sib_gated_dfts_e =
      ijtag_committed && dbg_disable_i.dft_secure && !sib_dfts_seen_q;
  wire sib_gated_dftn_e =
      ijtag_committed && dbg_disable_i.dft_nonsecure && !sib_dftn_seen_q;
  `OCAH_FCOV_COVER(c_sib_gating_enabled_dfd, sib_enabled_dfd_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sib_gating_enabled_dft_secure, sib_enabled_dfts_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sib_gating_enabled_dft_nonsecure, sib_enabled_dftn_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sib_gating_gated_dfd, sib_gated_dfd_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sib_gating_gated_dft_secure, sib_gated_dfts_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_sib_gating_gated_dft_nonsecure, sib_gated_dftn_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // stap_3dcr_cg — STAP type activity, stored 3DCR fields, chain behavior,
  // and security state. stap_sel_int is the stored select before the
  // security gate; a set sel_int with a clear sel means the gate is acting.
  // ------------------------------------------------------------------
  wire stap_type_io_e = stap_io_tdo_oen_i && !in_reset;
  wire stap_type_smc_e = stap_smc_tdo_oen_i && !in_reset;
  wire stap_type_sep_e = stap_sep_tdo_oen_i && !in_reset;
  wire stap_type_extra_e = stap_extra_tdo_oen_i && !in_reset;
  `OCAH_FCOV_COVER(c_stap_type_io, stap_type_io_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_stap_type_smc, stap_type_smc_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_stap_type_sep, stap_type_sep_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_stap_type_extra, stap_type_extra_e, tck_i, in_reset)

  wire any_sel_int = stap_io_sel_int_i || stap_smc_sel_int_i
      || stap_sep_sel_int_i || stap_extra_sel_int_i;
  wire any_sel = stap_io_sel_i || stap_smc_sel_i || stap_sep_sel_i
      || stap_extra_sel_i;
  wire any_tms_hold = stap_io_tms_hold_i || stap_smc_tms_hold_i
      || stap_sep_tms_hold_i || stap_extra_tms_hold_i;
  wire any_config_hold = stap_io_config_hold_i || stap_smc_config_hold_i
      || stap_sep_config_hold_i || stap_extra_config_hold_i;
  wire field_select_e = tap_3dcr_committed && any_sel_int;
  wire field_tms_hold_e = tap_3dcr_committed && any_tms_hold;
  wire field_config_hold_e = tap_3dcr_committed && any_config_hold;
  `OCAH_FCOV_COVER(c_3dcr_field_select, field_select_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_3dcr_field_tms_hold, field_tms_hold_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_3dcr_field_config_hold, field_config_hold_e, tck_i, in_reset)

  wire chain_sib_open_e = tap_3dcr_committed && any_sel_int;
  wire chain_sib_closed_e = tap_3dcr_committed && !any_sel_int;
  wire chain_selected_in_path_e = !in_reset && any_sel;
  `OCAH_FCOV_COVER(c_3dcr_chain_sib_open, chain_sib_open_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_3dcr_chain_sib_closed, chain_sib_closed_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_3dcr_chain_selected_stap_in_path, chain_selected_in_path_e, tck_i, in_reset)

  wire stap_security_enabled_e = !in_reset && any_sel;
  wire stap_security_gated_e = !in_reset
      && ((stap_io_sel_int_i && !stap_io_sel_i)
          || (stap_smc_sel_int_i && !stap_smc_sel_i)
          || (stap_sep_sel_int_i && !stap_sep_sel_i)
          || (stap_extra_sel_int_i && !stap_extra_sel_i));
  `OCAH_FCOV_COVER(c_stap_security_enabled, stap_security_enabled_e, tck_i, in_reset)
  `OCAH_FCOV_COVER(c_stap_security_gated_by_field, stap_security_gated_e, tck_i, in_reset)

  // ------------------------------------------------------------------
  // dbg_disable_cg cross-check mirror: each field exercised at both values
  // while out of reset. The 22-cell allowed/blocked contract with checker
  // gating stays in the Python ledger.
  // ------------------------------------------------------------------
  `define DTP_DBG_MIRROR(__field)                                                       \
    wire dbg_``__field``_clear_e = !in_reset && !dbg_disable_i.__field;           \
    wire dbg_``__field``_set_e = !in_reset && dbg_disable_i.__field;              \
    `OCAH_FCOV_COVER(c_dbg_disable_``__field``_clear, dbg_``__field``_clear_e,          \
                     tck_i, in_reset)                                                   \
    `OCAH_FCOV_COVER(c_dbg_disable_``__field``_set, dbg_``__field``_set_e,              \
                     tck_i, in_reset)

  `DTP_DBG_MIRROR(stap_io)
  `DTP_DBG_MIRROR(stap_smc)
  `DTP_DBG_MIRROR(stap_sep)
  `DTP_DBG_MIRROR(stap_extra)
  `DTP_DBG_MIRROR(stap_host)
  `DTP_DBG_MIRROR(dft_secure)
  `DTP_DBG_MIRROR(dft_nonsecure)
  `DTP_DBG_MIRROR(dfd)
  `DTP_DBG_MIRROR(smc_jtag2axi)
  `DTP_DBG_MIRROR(smc_otp_jtag2axi)
  `DTP_DBG_MIRROR(sep_otp_jtag2axi)
  `undef DTP_DBG_MIRROR

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups mirroring the cover-property bins.
  // ------------------------------------------------------------------
  covergroup cg_ijtag_sib with function sample (
      logic [2:0] pattern, logic dfd_gated, logic dfts_gated, logic dftn_gated
  );
    option.per_instance = 1;
    cp_pattern: coverpoint pattern {bins combo[] = {[0 : 7]};}
    cp_dfd_gated: coverpoint dfd_gated;
    cp_dfts_gated: coverpoint dfts_gated;
    cp_dftn_gated: coverpoint dftn_gated;
  endgroup

  covergroup cg_stap_3dcr with function sample (
      logic [3:0] sel_int, logic [3:0] sel, logic tms_hold, logic config_hold
  );
    option.per_instance = 1;
    cp_sel_int: coverpoint sel_int {
      bins none = {4'b0000};
      bins io = {4'b0001};
      bins smc = {4'b0010};
      bins sep = {4'b0100};
      bins extra = {4'b1000};
      bins multi = default;
    }
    cp_gated: coverpoint (sel_int & ~sel) != 4'b0;
    cp_tms_hold: coverpoint tms_hold;
    cp_config_hold: coverpoint config_hold;
  endgroup

  cg_ijtag_sib u_cg_ijtag_sib = new();
  cg_stap_3dcr u_cg_stap_3dcr = new();

  always_ff @(posedge tck_i) begin
    if (ijtag_committed) begin
      u_cg_ijtag_sib.sample({sib_dfd_seen_q, sib_dfts_seen_q, sib_dftn_seen_q},
                            dbg_disable_i.dfd && !sib_dfd_seen_q,
                            dbg_disable_i.dft_secure && !sib_dfts_seen_q,
                            dbg_disable_i.dft_nonsecure && !sib_dftn_seen_q);
    end
    if (tap_3dcr_committed) begin
      u_cg_stap_3dcr.sample(
          {stap_extra_sel_int_i, stap_sep_sel_int_i, stap_smc_sel_int_i, stap_io_sel_int_i}, {
          stap_extra_sel_i, stap_sep_sel_i, stap_smc_sel_i, stap_io_sel_i}, any_tms_hold,
          any_config_hold);
    end
  end
`endif

endmodule : dtp_scan_fcov
