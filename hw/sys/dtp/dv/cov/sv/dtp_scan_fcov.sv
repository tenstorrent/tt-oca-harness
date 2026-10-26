// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scan-network functional coverage: the iJTAG SIB network (cg_ijtag_sib),
// the STAP 3DCRs (cg_stap_3dcr), the STAP chain behind the PTAP 3DCR select
// (cg_stap_chain), CONFIG_HOLD across the TAP resets (cg_3dcr_hold), and the
// scan-side debug-disable cells (cg_dbg_disable_scan).
//
// One instance in the shared tb_top serves both flows. The iJTAG chain
// controls, the STAP host ports, and the extended STAP host shift enable are
// flattened DUT outputs. The SIB scan bits, each STAP's SIB and 3DCR, the
// PTAP 3DCR, and dbg_disable_sync_i, the TCK-synchronized disable vector the
// gates apply, come through hierarchical references.
//
// Every update event samples at the rising TCK edge that leaves Update-IR or
// Update-DR: the update stages load on the falling edge inside that state, so
// the stored values are the new ones, while a value registered on the edge
// that entered the state is the one the update acted on.
//
// The TAP reset is TRST AND power-on reset, as the PTAP combines them and
// forwards the result to the STAPs.
//
// CONVENTION: no declaration initializers on always_ff-driven variables;
// declare wires before use.

module dtp_scan_fcov (
  input wire        tck_i,
  input wire        tap_rst_ni,
  input wire [15:0] tap_state_i,
  input wire [63:0] inst_decoded_i,
  input wire sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_sync_i,

  // iJTAG chain controls (flattened DUT outputs)
  input wire dft_secure_select_i,
  input wire dft_secure_shift_en_i,
  input wire dft_select_i,
  input wire dft_shift_en_i,
  input wire dfd_select_i,
  input wire dfd_shift_en_i,

  // iJTAG SIB scan bits, the value an Update-DR loads (hierarchical references)
  input wire dft_secure_sib_bit_i,
  input wire dft_nonsecure_sib_bit_i,
  input wire dfd_sib_bit_i,

  // STAP legs and the extended STAP host shift enable (flattened DUT outputs)
  input wire stap_io_tdo_oen_i,
  input wire stap_smc_tdo_oen_i,
  input wire stap_sep_tdo_oen_i,
  input wire stap_extra_tdo_oen_i,
  input wire stap_host_shift_en_i,

  // STAP SIB and stored 3DCR state (hierarchical references)
  input wire stap_io_sib_i,
  input wire stap_io_sel_int_i,
  input wire stap_io_tms_hold_i,
  input wire stap_io_config_hold_i,
  input wire stap_smc_sib_i,
  input wire stap_smc_sel_int_i,
  input wire stap_smc_tms_hold_i,
  input wire stap_smc_config_hold_i,
  input wire stap_sep_sib_i,
  input wire stap_sep_sel_int_i,
  input wire stap_sep_tms_hold_i,
  input wire stap_sep_config_hold_i,
  input wire stap_extra_sib_i,
  input wire stap_extra_sel_int_i,
  input wire stap_extra_tms_hold_i,
  input wire stap_extra_config_hold_i,

  // PTAP 3DCR (hierarchical references)
  input wire ptap_stap_select_i,
  input wire ptap_config_hold_i
);

  localparam logic [63:0] SelectIjtagInstr = 64'h1 << 6'h1A;
  localparam logic [63:0] RunbistInstr = 64'h1 << 6'h02;

  // ------------------------------------------------------------------
  // Common scan decode.
  // ------------------------------------------------------------------
  wire in_reset = (tap_rst_ni !== 1'b1);
  logic [15:0] tap_state_q;
  logic in_reset_q;
  always_ff @(posedge tck_i) begin
    tap_state_q <= tap_state_i;
    in_reset_q  <= in_reset;
  end
  wire [15:0] tap_state_prev = tap_state_q;
  wire update_dr = !in_reset && (tap_state_i == jtag_tap_pkg::UPDATE_DR);
  wire update_ir = !in_reset && (tap_state_i == jtag_tap_pkg::UPDATE_IR);
  wire shifting = !in_reset
      && ((tap_state_i == jtag_tap_pkg::SHIFT_DR) || (tap_state_i == jtag_tap_pkg::SHIFT_IR));
  wire capturing = (tap_state_i == jtag_tap_pkg::CAPTURE_DR)
      || (tap_state_i == jtag_tap_pkg::CAPTURE_IR);

  // ------------------------------------------------------------------
  // cg_ijtag_sib: one sample per Update-DR of the iJTAG network, which the
  // PTAP selects as its DR under SELECT_IJTAG and RUNBIST. SIB vectors are
  // {dft_secure, dft_nonsecure, dfd}, the TDI-to-TDO order. The DR select is
  // high in Update-DR, so a SIB's host select there is its open state after
  // the update.
  // ------------------------------------------------------------------
  wire ijtag_runbist = |(inst_decoded_i & RunbistInstr);
  wire ijtag_update = update_dr && |(inst_decoded_i & (SelectIjtagInstr | RunbistInstr));
  wire [2:0] sib_open = {dft_secure_select_i, dft_select_i, dfd_select_i};
  wire [2:0] sib_gated = {
    dbg_disable_sync_i.dft_secure, dbg_disable_sync_i.dft_nonsecure, dbg_disable_sync_i.dfd
  };
  wire [2:0] sib_access = sib_open & {dft_secure_shift_en_i, dft_shift_en_i, dfd_shift_en_i};
  // Instruments shifted through their open SIB since Capture.
  logic [2:0] sib_shifted_q;
  always_ff @(posedge tck_i) sib_shifted_q <= capturing ? 3'b000 : (sib_shifted_q | sib_access);
  wire [2:0] sib_shifted = sib_shifted_q;

  // ------------------------------------------------------------------
  // cg_stap_3dcr: one sample per STAP at each update the STAP chain takes,
  // which needs the PTAP 3DCR select before the update; the chain shifts on
  // IR and DR scans alike. A STAP's 3DCR is in the chain while its SIB is
  // open, and the SIB opens or closes at that same update, so the SIB state
  // is the one registered on entry. STAP vectors are {extra, sep, smc, io}.
  // ------------------------------------------------------------------
  wire [3:0] stap_sib = {stap_extra_sib_i, stap_sep_sib_i, stap_smc_sib_i, stap_io_sib_i};
  wire [3:0] stap_sel_int = {
    stap_extra_sel_int_i, stap_sep_sel_int_i, stap_smc_sel_int_i, stap_io_sel_int_i
  };
  wire [3:0] stap_tms_hold = {
    stap_extra_tms_hold_i, stap_sep_tms_hold_i, stap_smc_tms_hold_i, stap_io_tms_hold_i
  };
  wire [3:0] stap_config_hold = {
    stap_extra_config_hold_i, stap_sep_config_hold_i, stap_smc_config_hold_i, stap_io_config_hold_i
  };
  wire [3:0] stap_tdo_oen = {
    stap_extra_tdo_oen_i, stap_sep_tdo_oen_i, stap_smc_tdo_oen_i, stap_io_tdo_oen_i
  };
  wire [3:0] stap_gated = {
    dbg_disable_sync_i.stap_extra,
    dbg_disable_sync_i.stap_sep,
    dbg_disable_sync_i.stap_smc,
    dbg_disable_sync_i.stap_io
  };
  logic ptap_select_q;
  logic [3:0] stap_sib_q;
  // Ports that drove tdo_oen since Capture.
  logic [3:0] stap_fwd_q;
  always_ff @(posedge tck_i) begin
    ptap_select_q <= ptap_stap_select_i;
    stap_sib_q    <= stap_sib;
    stap_fwd_q    <= capturing ? 4'b0000 : (stap_fwd_q | stap_tdo_oen);
  end
  wire ptap_select_before = ptap_select_q;
  wire [3:0] stap_sib_before = stap_sib_q;
  wire [3:0] stap_forwarded = stap_fwd_q;
  wire stap_chain_update = (update_dr || update_ir) && ptap_select_before;

  // ------------------------------------------------------------------
  // cg_3dcr_hold: CONFIG_HOLD across the TAP resets. Each 3DCR image is
  // {config_hold, select, tms_hold}, PTAP first (it has no tms_hold), and
  // only a non-zero image is sampled. The snapshot holds the images from the
  // last edge outside the TAP reset. A TMS walk enters Test-Logic-Reset only
  // from Select-IR-Scan and resets the 3DCRs on the falling edge inside the
  // first Test-Logic-Reset cycle, so the edge leaving that cycle compares the
  // snapshot taken on entry with the result; a TAP reset, TRST or power-on
  // reset, compares on the first edge after its release.
  // ------------------------------------------------------------------
  localparam int unsigned HoldRegs = 5;
  wire [3*HoldRegs-1:0] tdcr_image = {
    stap_extra_config_hold_i,
    stap_extra_sel_int_i,
    stap_extra_tms_hold_i,
    stap_sep_config_hold_i,
    stap_sep_sel_int_i,
    stap_sep_tms_hold_i,
    stap_smc_config_hold_i,
    stap_smc_sel_int_i,
    stap_smc_tms_hold_i,
    stap_io_config_hold_i,
    stap_io_sel_int_i,
    stap_io_tms_hold_i,
    ptap_config_hold_i,
    ptap_stap_select_i,
    1'b0
  };
  logic [3*HoldRegs-1:0] tdcr_snap_q;
  always_ff @(posedge tck_i) begin
    if (!in_reset) tdcr_snap_q <= tdcr_image;
  end
  wire [3*HoldRegs-1:0] tdcr_before = tdcr_snap_q;
  wire tlr_reset = !in_reset && (tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET)
      && (tap_state_prev == jtag_tap_pkg::SELECT_IR_SCAN);
  wire trst_reset = !in_reset && in_reset_q;
  logic [HoldRegs-1:0] hold_loaded, hold_held, hold_ok;
  always_comb begin
    for (int unsigned k = 0; k < HoldRegs; k++) begin
      hold_loaded[k] = |tdcr_before[3*k+:3];
      hold_held[k] = tdcr_before[3*k+2];
      hold_ok[k] = (trst_reset || !hold_held[k]) ? (tdcr_image[3*k+:3] == 3'b000)
                                                 : (tdcr_image[3*k+:3] == tdcr_before[3*k+:3]);
    end
  end

  // ------------------------------------------------------------------
  // cg_dbg_disable_scan: the scan-side debug-disable cells at signal level.
  // Field order: stap_io, stap_smc, stap_sep, stap_extra, stap_host,
  // dft_secure, dft_nonsecure, dfd. An attempt and its outcome:
  //   * STAP port field: a STAP chain shift cycle while the port's stored
  //     select is set; allowed when the port drives tdo_oen, blocked when it
  //     stays parked.
  //   * stap_host: a STAP chain shift cycle; allowed when the extended host
  //     shift enable follows it, blocked when that enable stays low.
  //   * SIB field: an iJTAG network Update-DR that loads a 1 into the SIB
  //     bit; allowed when the SIB opens, blocked when it stays closed.
  // A release is the disable clearing after a blocked attempt; a recovery
  // is the first allowed attempt after a release.
  // ------------------------------------------------------------------
  localparam int unsigned ScanFields = 8;
  wire stap_chain_shift = shifting && ptap_stap_select_i;
  wire [ScanFields-1:0] scan_disable = {
    dbg_disable_sync_i.dfd,
    dbg_disable_sync_i.dft_nonsecure,
    dbg_disable_sync_i.dft_secure,
    dbg_disable_sync_i.stap_host,
    stap_gated
  };
  wire [ScanFields-1:0] dbg_attempt = {
    ijtag_update && dfd_sib_bit_i,
    ijtag_update && dft_nonsecure_sib_bit_i,
    ijtag_update && dft_secure_sib_bit_i,
    stap_chain_shift,
    {4{stap_chain_shift}} & stap_sel_int
  };
  wire [ScanFields-1:0] dbg_blocked = {
    !dfd_select_i, !dft_select_i, !dft_secure_select_i, !stap_host_shift_en_i, ~stap_tdo_oen
  };
  wire [3:0] scan_disable_count = 4'($countones(scan_disable));
  logic [ScanFields-1:0] scan_disable_q, dbg_blocked_seen_q, dbg_released_q;
  wire [ScanFields-1:0] scan_disable_before = scan_disable_q;
  wire [ScanFields-1:0] dbg_release = {ScanFields{!in_reset}} & scan_disable_before
      & ~scan_disable & dbg_blocked_seen_q;
  wire [ScanFields-1:0] dbg_recover = dbg_attempt & ~dbg_blocked & dbg_released_q;
  always_ff @(posedge tck_i) begin
    scan_disable_q     <= scan_disable;
    dbg_blocked_seen_q <= (dbg_blocked_seen_q & ~dbg_release) | (dbg_attempt & dbg_blocked);
    dbg_released_q     <= (dbg_released_q & ~dbg_recover) | dbg_release;
  end

  // ------------------------------------------------------------------
  // Covergroups, under the cross rules dtp_fcov.sv states, sampled on the
  // events decoded above.
  // ------------------------------------------------------------------
  // Each SIB state is {disable, open}: a SIB whose disable is set is held
  // closed, so an open SIB under its disable is a design failure.
  covergroup cg_ijtag_sib with function sample (
      logic is_runbist,
      logic [2:0] open_sibs,
      logic [2:0] shifted_sibs,
      logic [1:0] dft_secure_state,
      logic [1:0] dft_nonsecure_state,
      logic [1:0] dfd_state
  );
    option.per_instance = 1;
    cp_instr: coverpoint is_runbist {bins select_ijtag = {1'b0}; bins runbist = {1'b1};}
    // {dft_secure, dft_nonsecure, dfd} open after the update.
    cp_pattern: coverpoint open_sibs {
      bins pattern[] = {[0 : 7]};
    }
    cp_access: coverpoint shifted_sibs {
      wildcard bins dft_secure = {3'b1??};
      wildcard bins dft_nonsecure = {3'b?1?};
      wildcard bins dfd = {3'b??1};
    }
    cp_dft_secure: coverpoint dft_secure_state {
      bins closed = {2'b00};
      bins open = {2'b01};
      bins gated = {2'b10};
      illegal_bins open_while_gated = {2'b11};
    }
    cp_dft_nonsecure: coverpoint dft_nonsecure_state {
      bins closed = {2'b00};
      bins open = {2'b01};
      bins gated = {2'b10};
      illegal_bins open_while_gated = {2'b11};
    }
    cp_dfd: coverpoint dfd_state {
      bins closed = {2'b00};
      bins open = {2'b01};
      bins gated = {2'b10};
      illegal_bins open_while_gated = {2'b11};
    }
    x_gating: cross cp_dft_secure, cp_dft_nonsecure, cp_dfd;
  endgroup

  // The 3DCR fields are the stored ones; is_gated is the STAP's disable.
  covergroup cg_stap_3dcr with function sample (
      logic [1:0] stap,
      logic sib_open,
      logic is_forwarded,
      logic sel,
      logic tms_hold,
      logic config_hold,
      logic is_gated
  );
    option.per_instance = 1;
    cp_type: coverpoint stap {
      bins io = {2'd0}; bins smc = {2'd1}; bins sep = {2'd2}; bins extra = {2'd3};
    }
    cp_sib: coverpoint sib_open {bins closed = {1'b0}; bins open = {1'b1};}
    cp_forwarded: coverpoint is_forwarded {bins forwarded = {1'b1};}
    cp_select: coverpoint sel iff (sib_open) {bins deselected = {1'b0}; bins selected = {1'b1};}
    cp_tms_hold: coverpoint tms_hold iff (sib_open) {bins low = {1'b0}; bins high = {1'b1};}
    cp_config_hold: coverpoint config_hold iff (sib_open) {bins clear = {1'b0}; bins set = {1'b1};}
    cp_security: coverpoint is_gated iff (sib_open) {bins enabled = {1'b0}; bins gated = {1'b1};}
    x_type_sib: cross cp_type, cp_sib;
    x_type_forwarded: cross cp_type, cp_forwarded;
    x_config: cross cp_type, cp_select, cp_tms_hold, cp_config_hold, cp_security iff (sib_open);
  endgroup

  // One sample per Update-IR and Update-DR, with the PTAP 3DCR select the
  // scan ran under. With it clear the STAP chain held its state.
  covergroup cg_stap_chain with function sample (logic ptap_select, logic dr_scan);
    option.per_instance = 1;
    cp_ptap_select: coverpoint ptap_select {
      bins held_unselected = {1'b0}; bins scanned_selected = {1'b1};
    }
    cp_scan: coverpoint dr_scan {bins ir = {1'b0}; bins dr = {1'b1};}
    x_chain: cross cp_ptap_select, cp_scan;
  endgroup

  // hold_case is {ok, trst, held}: ok is the result the reset and
  // CONFIG_HOLD call for (the TAP reset clears, Test-Logic-Reset clears unless
  // CONFIG_HOLD is set); any other result is a design failure.
  covergroup cg_3dcr_hold with function sample (logic [2:0] reg_idx, logic [2:0] hold_case);
    option.per_instance = 1;
    cp_reg: coverpoint reg_idx {
      bins ptap = {3'd0};
      bins io = {3'd1};
      bins smc = {3'd2};
      bins sep = {3'd3};
      bins extra = {3'd4};
    }
    cp_case: coverpoint hold_case {
      bins tlr_unheld_cleared = {3'b100};
      bins tlr_held_retained = {3'b101};
      bins trst_unheld_cleared = {3'b110};
      bins trst_held_cleared = {3'b111};
      illegal_bins wrong_result = {[3'b000 : 3'b011]};
    }
    x_hold: cross cp_reg, cp_case;
  endgroup

  localparam logic [1:0] PhaseAttempt = 2'd0;
  localparam logic [1:0] PhaseRelease = 2'd1;
  localparam logic [1:0] PhaseRecovery = 2'd2;

  covergroup cg_dbg_disable_scan with function sample (
      logic [2:0] field,
      logic [1:0] phase,
      logic disabled,
      logic is_blocked,
      logic [3:0] disabled_count,
      logic others_disabled
  );
    option.per_instance = 1;
    cp_field: coverpoint field {
      bins stap_io = {3'd0};
      bins stap_smc = {3'd1};
      bins stap_sep = {3'd2};
      bins stap_extra = {3'd3};
      bins stap_host = {3'd4};
      bins dft_secure = {3'd5};
      bins dft_nonsecure = {3'd6};
      bins dfd = {3'd7};
    }
    cp_value: coverpoint disabled iff (phase == PhaseAttempt) {
      bins clear = {1'b0}; bins set = {1'b1};
    }
    // {disabled, is_blocked}: an outcome that contradicts the disable is a
    // design failure.
    cp_outcome: coverpoint {
      disabled, is_blocked
    } iff (phase == PhaseAttempt) {
      bins allowed = {2'b00};
      bins blocked = {2'b11};
      illegal_bins clear_blocked = {2'b01};
      illegal_bins set_allowed = {2'b10};
    }
    cp_mask: coverpoint disabled_count iff (phase == PhaseAttempt) {
      bins all_clear = {4'd0};
      bins one_hot = {4'd1};
      bins multi_hot = {[4'd2 : 4'd7]};
      bins all_disabled = {4'd8};
    }
    cp_isolation: coverpoint others_disabled iff (phase == PhaseAttempt && !disabled) {
      bins other_field_set = {1'b1};
    }
    cp_sequence: coverpoint phase iff (phase != PhaseAttempt) {
      bins released = {PhaseRelease}; bins recovered = {PhaseRecovery};
    }
    x_cell: cross cp_field, cp_value iff (phase == PhaseAttempt);
    x_field_isolation: cross cp_field, cp_isolation iff (phase == PhaseAttempt && !disabled);
    x_sequence: cross cp_field, cp_sequence iff (phase != PhaseAttempt);
  endgroup

  wire [1:0] sib_dft_secure_state = {sib_gated[2], sib_open[2]};
  wire [1:0] sib_dft_nonsecure_state = {sib_gated[1], sib_open[1]};
  wire [1:0] sib_dfd_state = {sib_gated[0], sib_open[0]};

  cg_ijtag_sib u_cg_ijtag_sib = new();
  cg_stap_3dcr u_cg_stap_3dcr = new();
  cg_stap_chain u_cg_stap_chain = new();
  cg_3dcr_hold u_cg_3dcr_hold = new();
  cg_dbg_disable_scan u_cg_dbg_disable_scan = new();

  always_ff @(posedge tck_i) begin
    if (ijtag_update) begin
      u_cg_ijtag_sib.sample(ijtag_runbist, sib_open, sib_shifted, sib_dft_secure_state,
                            sib_dft_nonsecure_state, sib_dfd_state);
    end
    if (stap_chain_update) begin
      for (int unsigned s = 0; s < 4; s++) begin
        u_cg_stap_3dcr.sample(2'(s), stap_sib_before[s], stap_forwarded[s], stap_sel_int[s],
                              stap_tms_hold[s], stap_config_hold[s], stap_gated[s]);
      end
    end
    if (update_dr || update_ir) begin
      u_cg_stap_chain.sample(ptap_select_before, update_dr);
    end
    if (tlr_reset || trst_reset) begin
      for (int unsigned k = 0; k < HoldRegs; k++) begin
        if (hold_loaded[k]) begin
          u_cg_3dcr_hold.sample(3'(k), {hold_ok[k], trst_reset, hold_held[k]});
        end
      end
    end
    for (int unsigned f = 0; f < ScanFields; f++) begin
      if (dbg_attempt[f]) begin
        u_cg_dbg_disable_scan.sample(3'(f), PhaseAttempt, scan_disable[f], dbg_blocked[f],
                                     scan_disable_count, |(scan_disable & ~(ScanFields'(1) << f)));
      end
      if (dbg_release[f]) begin
        u_cg_dbg_disable_scan.sample(3'(f), PhaseRelease, scan_disable[f], dbg_blocked[f],
                                     scan_disable_count, 1'b0);
      end
      if (dbg_recover[f]) begin
        u_cg_dbg_disable_scan.sample(3'(f), PhaseRecovery, scan_disable[f], dbg_blocked[f],
                                     scan_disable_count, 1'b0);
      end
    end
  end

endmodule : dtp_scan_fcov
