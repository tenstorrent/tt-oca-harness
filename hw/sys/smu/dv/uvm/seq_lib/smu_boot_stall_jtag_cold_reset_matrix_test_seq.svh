// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_boot_stall_jtag_cold_reset_matrix_test scenario sequence (the
// DEBUG_CONTROL boot stall across cold reset, TRST and the GPIO pad),
// carrying the cocotb cocotb_wrapper/tests/
// smu_boot_stall_jtag_cold_reset_matrix_test.py semantics on the SMC eFuse
// controller's real sense (no +skip_fuse_sense): every fuse-reset compare is
// anchored on smc_fuse_sense_done_o 0 -> 1 after the primary reset it
// follows, and a release after a clear is bounded by the gate path (about
// 20 clk_smc), not the sense.
//
//   S1 baseline: TAP reset, the fuse reset released after the bring-up sense
//      (CHK-STALL-BASELINE);
//   S2 DEBUG_CONTROL boot_stall=1/boot_stall_ovrd=1, read back through the
//      TDR and on the SMC exports (CHK-DEBUG-CONTROL-READBACK);
//   S3 cold reset with TRST high: the stall survives (the TDR lives in the
//      TCK domain), and the gate reads 0 on every one of the hold-window
//      clocks after the sense completes (CHK-STALL-STICKY);
//   S4 TRST pulse clears DEBUG_CONTROL; with the sense already done the
//      release follows within the gate path and holds, and the measured
//      release fits inside the hold window the S3 claim rests on
//      (CHK-STALL-TRST);
//   S5 re-asserting the stall without a primary reset does not re-gate the
//      released fuse reset (CHK-STALL-REASSERT);
//   S6 the GPIO boot-stall pad alone, across a cold reset, gates the fuse
//      reset while the JTAG override is idle -- the positive control for the
//      two legs that follow (CHK-STALL-PAD-ONLY);
//   S7 both sources asserted agree and the gate stays shut
//      (CHK-STALL-BOTH-SOURCES);
//   S8 the override forced low while the pad still drives 1 opens the gate:
//      the SMC combines the two as ovrd ? jtag_val : pad
//      (CHK-STALL-OVRD-MASKS-PAD);
//   TIMEOUT the bounded-wait inventory (CHK-TIMEOUT-PATHS) and the ordered
//      step fence (CHK-NONVAC).
//
// Independently, the always-on scoreboard's debug_control_tdr feature
// predicts the capture of every DEBUG_CONTROL scan from the register shadow
// and the TAP resets seen, and its boot_gate feature requires the boot gate
// open and the sense complete at every fuse-reset release the pin monitor
// observes; +SMU_DEBUG_CONTROL_SCOREBOARD_NEGATIVE and
// +SMU_BOOT_GATE_SCOREBOARD_NEGATIVE corrupt those predictions so the run
// must FAIL.

class smu_boot_stall_jtag_cold_reset_matrix_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_boot_stall_jtag_cold_reset_matrix_test_seq)

  localparam string ChkBaseline = "CHK-STALL-BASELINE";
  localparam string ChkReadback = "CHK-DEBUG-CONTROL-READBACK";
  localparam string ChkSticky = "CHK-STALL-STICKY";
  localparam string ChkTrst = "CHK-STALL-TRST";
  localparam string ChkReassert = "CHK-STALL-REASSERT";
  localparam string ChkPadOnly = "CHK-STALL-PAD-ONLY";
  localparam string ChkBothSources = "CHK-STALL-BOTH-SOURCES";
  localparam string ChkOvrdMasksPad = "CHK-STALL-OVRD-MASKS-PAD";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";
  localparam string ChkNonvac = "CHK-NONVAC";

  // DEBUG_CONTROL scans a pass issues: S2 write + readback, S5 write +
  // clear, S7 write, S8 write + clear -- each one capture the
  // debug_control_tdr predictor compares.
  localparam int unsigned DebugControlScansPerPass = 7;
  // Fuse-reset releases a pass causes: S4 (TRST clear) and S8 (override low).
  localparam int unsigned FuseReleasesPerPass = 2;
  // Bounded-wait sites: s1_rti, s1_fuse_baseline, s3_sense_done,
  // s3_primary, s4_release, s6_sense_done, s6_primary, s8_release.
  localparam int unsigned ExpectedTimeoutPaths = 8;
  // Step marks S1..S8, TIMEOUT, PASS: nine ordered, non-decreasing deltas.
  localparam int unsigned ExpectedStepDeltas = 9;

  function new(string name = "smu_boot_stall_jtag_cold_reset_matrix_test_seq");
    super.new(name);
  endfunction

  task body();
    seed_scenario_rng();
    attach_evidence('{ChkBaseline, ChkReadback, ChkSticky, ChkTrst, ChkReassert, ChkPadOnly,
                    ChkBothSources, ChkOvrdMasksPad, ChkTimeoutPaths, ChkNonvac, ChkSbMinAct});
    check_min_activity(SmuFeatureDebugControlTdr, DebugControlScansPerPass);
    check_min_activity(SmuFeatureBootGate, FuseReleasesPerPass);
    `uvm_info(get_type_name(), $sformatf(
              {"SMU SV-UVM boot-stall matrix (smu_boot_stall_jtag_cold_reset_matrix_test): ",
               "sense_bound=%0d release_bound=%0d hold=%0d clk_smu; scenario_seed=%0d"},
              test_cfg.fuse_sense_bound_cycles, test_cfg.fuse_gate_release_bound_cycles,
              test_cfg.fuse_gate_hold_cycles, scenario_seed), UVM_LOW)

    run_baseline();
    run_stall_write();
    run_cold_with_stall();
    run_trst_clear();
    run_reassert();
    run_pad_only();
    run_both_sources();
    run_override_masks_pad();
    run_timeout_inventory(ChkTimeoutPaths, ExpectedTimeoutPaths);

    mark_step("PASS", "scenario complete (PASS term recorded for the NONVAC fence)");
    check_evidence(ChkNonvac, "ordered step-delta count", 64'(ordered_step_deltas()),
                   64'(ExpectedStepDeltas), $sformatf("steps=%0d", m_step_order.size()));
    finalize_evidence();
  endtask

  // S1: TAP reset; the bring-up sense done and the fuse reset released.
  protected task run_baseline();
    bit [15:0] last;
    int cycles;
    mark_step("S1", "BASELINE: TAP reset then Run-Test/Idle; fuse reset released after the sense");
    tap_reset();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s1_rti", 1'b0, last);
    wait_pin_level("fuse_reset_n_delayed", 1'b1,
                   test_cfg.fuse_sense_bound_cycles + test_cfg.fuse_gate_release_bound_cycles,
                   "s1_fuse_baseline", cycles);
    check_evidence(ChkBaseline, "fuse reset released", 64'(pin_is("fuse_reset_n_delayed", 1'b1)),
                   64'd1, $sformatf("after %0d smu clocks", cycles));
    check_evidence(ChkBaseline, "fuse sense done", 64'(pin_is("fuse_sense_done", 1'b1)), 64'd1);
    check_evidence(ChkBaseline, "stall ovrd idle", 64'(pin_is("jtag_boot_stall_ovrd", 1'b0)),
                   64'd1);
  endtask

  // S2: the stall through the TDR, read back on the TDR and on the exports.
  protected task run_stall_write();
    bit [SmuDebugControlLen-1:0] image = smu_debug_control_image(1'b1, 1'b1);
    bit [SmuDebugControlLen-1:0] readback;
    mark_step("S2", "STALL: DEBUG_CONTROL boot_stall=1 boot_stall_ovrd=1");
    debug_control_write(image);
    debug_control_scan(image, readback);
    check_evidence(ChkReadback, "DEBUG_CONTROL readback", 64'(readback & SmuDebugControlRwMask),
                   64'(image), $sformatf("raw=0x%02h", readback));
    check_stall_exports(ChkReadback, "before cold", 1'b1, 1'b1);
  endtask

  // S3: cold reset with TRST high; the stall is sticky and gates the
  // sensed release.
  protected task run_cold_with_stall();
    int unsigned breaks;
    mark_step("S3", "COLD+STALL: cold reset with TRST held high; stall sticky; fuse reset gated");
    cold_reset_and_sense("s3_sense_done", "s3_primary");
    hold_pin_level("fuse_reset_n_delayed", 1'b0, test_cfg.fuse_gate_hold_cycles, breaks);
    check_evidence(ChkSticky, "fuse reset gated after the sense", 64'(breaks), 64'd0, $sformatf(
                   "hold=%0d clk_smu sense_done=%0b", test_cfg.fuse_gate_hold_cycles,
                   pin_is("fuse_sense_done", 1'b1)));
    check_stall_exports(ChkSticky, "survives cold (TRST high)", 1'b1, 1'b1);
  endtask

  // S4: TRST clears DEBUG_CONTROL; the gate opens within the gate path.
  protected task run_trst_clear();
    int release_cycles;
    mark_step("S4",
              "TRST: TAP reset clears DEBUG_CONTROL; fuse reset releases within the gate path");
    arm_gate_release(ChkTrst, "before TRST");
    tap_reset();
    wait_smu_cycles(TdrExportSettleCycles);
    check_stall_exports(ChkTrst, "cleared by TRST", 1'b0, 1'b0);
    expect_gate_release(ChkTrst, "after TRST", "s4_release", release_cycles);
  endtask

  // S5: a re-asserted stall does not re-gate a released fuse reset.
  protected task run_reassert();
    int unsigned breaks;
    mark_step("S5",
              "REASSERT: stall re-asserted without a primary reset; fuse reset stays released");
    debug_control_write(smu_debug_control_image(1'b1, 1'b1));
    check_stall_exports(ChkReassert, "re-asserted", 1'b1, 1'b1);
    hold_pin_level("fuse_reset_n_delayed", 1'b1, test_cfg.fuse_gate_hold_cycles, breaks);
    check_evidence(ChkReassert, "fuse reset stays released on the sticky re-assert", 64'(breaks),
                   64'd0, $sformatf("hold=%0d clk_smu", test_cfg.fuse_gate_hold_cycles));
    debug_control_write('0);
  endtask

  // S6: the GPIO pad alone gates the release across a cold reset.
  protected task run_pad_only();
    int unsigned breaks;
    mark_step("S6",
              "PAD-ONLY: GPIO boot-stall pad driving across a cold reset; JTAG override idle");
    tb_vif.gpio_boot_stall_drive <= 1'b1;
    wait_smu_cycles(8);
    cold_reset_and_sense("s6_sense_done", "s6_primary");
    hold_pin_level("fuse_reset_n_delayed", 1'b0, test_cfg.fuse_gate_hold_cycles, breaks);
    check_evidence(ChkPadOnly, "fuse reset gated by the pad after the sense", 64'(breaks), 64'd0,
                   $sformatf("hold=%0d clk_smu", test_cfg.fuse_gate_hold_cycles));
    check_evidence(ChkPadOnly, "jtag ovrd idle", 64'(pin_is("jtag_boot_stall_ovrd", 1'b0)), 64'd1);
  endtask

  // S7: both sources asserted agree; the gate stays shut.
  protected task run_both_sources();
    int unsigned breaks;
    mark_step("S7", "BOTH: pad driving and JTAG stall asserted; fuse reset stays gated");
    debug_control_write(smu_debug_control_image(1'b1, 1'b1));
    check_stall_exports(ChkBothSources, "both sources", 1'b1, 1'b1);
    hold_pin_level("fuse_reset_n_delayed", 1'b0, test_cfg.fuse_gate_hold_cycles, breaks);
    check_evidence(ChkBothSources, "fuse reset gated with both sources", 64'(breaks), 64'd0,
                   $sformatf("hold=%0d clk_smu", test_cfg.fuse_gate_hold_cycles));
  endtask

  // S8: the override forced low wins over the pad; the gate opens.
  protected task run_override_masks_pad();
    int release_cycles;
    mark_step("S8", "OVRD-LOW: boot_stall_ovrd=1 boot_stall=0 over the driving pad opens the gate");
    arm_gate_release(ChkOvrdMasksPad, "before override low");
    debug_control_write(smu_debug_control_image(1'b0, 1'b1));
    check_stall_exports(ChkOvrdMasksPad, "override low", 1'b1, 1'b0);
    expect_gate_release(ChkOvrdMasksPad, "after override low", "s8_release", release_cycles);
    tb_vif.gpio_boot_stall_drive <= 1'b0;
    debug_control_write('0);
  endtask

  // ------------------------------------------------------------------
  // Helpers.
  // ------------------------------------------------------------------

  protected function void check_stall_exports(string check_id, string when, bit ovrd, bit stall);
    check_evidence(check_id, {"jtag_boot_stall_ovrd ", when}, 64'(tb_vif.jtag_boot_stall_ovrd),
                   64'(ovrd));
    check_evidence(check_id, {"jtag_boot_stall ", when}, 64'(tb_vif.jtag_boot_stall), 64'(stall));
  endfunction

  // A cold-reset pulse, then the sense of this primary reset observed
  // 0 -> 1 within its bound, then the primary reset release.
  protected task cold_reset_and_sense(string sense_label, string primary_label);
    int sense_cycles, primary_cycles;
    pulse_cold_reset();
    if (!pin_is("fuse_sense_done", 1'b0))
      `uvm_error(get_type_name(), "fuse_sense_done not 0 after the cold-reset release")
    wait_pin_rise("fuse_sense_done", test_cfg.fuse_sense_bound_cycles, sense_label, sense_cycles);
    `uvm_info(get_type_name(), $sformatf(
              "FUSE-SENSE %s: smc_fuse_sense_done_o rose after %0d clk_smu (bound %0d)",
              sense_label, sense_cycles, test_cfg.fuse_sense_bound_cycles), UVM_LOW)
    wait_pin_level("rst_primary_smc_clk_n", 1'b1, test_cfg.reset_release_timeout_cycles,
                   primary_label, primary_cycles);
  endtask

  // Immediately before a clear stimulus: the sense is done and the gate shut.
  protected function void arm_gate_release(string check_id, string when);
    check_evidence(check_id, {"sense done ", when}, 64'(pin_is("fuse_sense_done", 1'b1)), 64'd1);
    check_evidence(check_id, {"gate shut ", when}, 64'(pin_is("fuse_reset_n_delayed", 1'b0)),
                   64'd1);
  endfunction

  // After the clear stimulus: the release within the gate-path bound, held
  // for the hold window, and the measured release inside that window so the
  // hold checks of this scenario can fail.
  protected task expect_gate_release(string check_id, string when, string label,
                                     output int release_cycles);
    int unsigned breaks;
    wait_pin_level("fuse_reset_n_delayed", 1'b1, test_cfg.fuse_gate_release_bound_cycles, label,
                   release_cycles);
    check_evidence(check_id, {"fuse reset released ", when}, 64'(pin_is("fuse_reset_n_delayed",
                                                                        1'b1)), 64'd1, $sformatf(
                   "release=%0d clk_smu bound=%0d", release_cycles,
                   test_cfg.fuse_gate_release_bound_cycles));
    hold_pin_level("fuse_reset_n_delayed", 1'b1, test_cfg.fuse_gate_hold_cycles, breaks);
    check_evidence(check_id, {"fuse reset held released ", when}, 64'(breaks), 64'd0);
    check_evidence(check_id, {"release inside the hold window ", when},
                   64'((release_cycles >= 0) &&
                       (release_cycles < int'(test_cfg.fuse_gate_hold_cycles))), 64'd1, $sformatf(
                   "release=%0d hold=%0d", release_cycles, test_cfg.fuse_gate_hold_cycles));
  endtask

endclass : smu_boot_stall_jtag_cold_reset_matrix_test_seq
