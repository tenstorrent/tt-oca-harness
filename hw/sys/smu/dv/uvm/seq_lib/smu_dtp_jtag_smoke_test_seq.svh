// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_dtp_jtag_smoke_test scenario sequence (SMU_ALL_005, DTP-JTAG-PTAP
// S1/S2/S3 on the embedded DTP's primary TAP), carrying the cocotb
// seq_lib/smu_dtp_jtag_smoke_test_seq.py semantics: S1 TAP reset to
// Run-Test/Idle; S2 IDCODE against the SMU-configured value
// (CHK-DTP-JTAG-PTAP-S1); S3 BYPASS one-TCK latency on the directed pattern
// leg by leg, then on random_count seeded patterns (CHK-DTP-JTAG-PTAP-S2;
// +SMU_RANDOM_COUNT, default 5); S4 TRST and power-on reset from Shift-DR
// back to Test-Logic-Reset (CHK-DTP-JTAG-PTAP-S3); S5 bounded-wait inventory
// (CHK-TIMEOUT-PATHS) and the ordered step fence S1<S2<S3<S4<S5<PASS
// (CHK-NONVAC). Each run_* task below carries its step's detail.
// Independently, the embedded DTP reference models predict every IDCODE and
// BYPASS DR scan and the decoded instruction of every IR load, paired by
// the always-on scoreboard; +SMU_PTAP_IDCODE_NEGATIVE corrupts the expected
// IDCODE in both the reference model and this sequence, so the run must
// FAIL.

class smu_dtp_jtag_smoke_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_dtp_jtag_smoke_test_seq)

  localparam string ChkPtapS1 = "CHK-DTP-JTAG-PTAP-S1";
  localparam string ChkPtapS2 = "CHK-DTP-JTAG-PTAP-S2";
  localparam string ChkPtapS3 = "CHK-DTP-JTAG-PTAP-S3";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";
  localparam string ChkNonvac = "CHK-NONVAC";

  // The cocotb scenario's directed BYPASS pattern and width.
  localparam bit [31:0] BypassPattern = 32'hA5A5_A5A5;
  localparam int unsigned BypassWidth = 32;
  localparam int unsigned IdcodeWidth = 32;
  // Bounded-wait sites of one pass: s1_rti, s2_idcode_rti, s3_select_dr,
  // s3_capture_dr, s3_shift_dr, s3_update_dr, s3_back_rti, s4_trst_tlr,
  // s4_por_tlr (cocotb EXPECTED_TIMEOUT_PATHS).
  localparam int unsigned ExpectedTimeoutPaths = 9;
  // Step marks S1..S5 plus PASS: five ordered, non-decreasing deltas.
  localparam int unsigned ExpectedStepDeltas = 5;

  function new(string name = "smu_dtp_jtag_smoke_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [31:0] expected_idcode;
    bit [15:0] last;

    seed_scenario_rng();
    attach_evidence('{ChkPtapS1, ChkPtapS2, ChkPtapS3, ChkTimeoutPaths, ChkNonvac});
    expected_idcode = smu_ptap_expected_idcode(test_cfg.ptap_idcode_negative);
    `uvm_info(get_type_name(),
              $sformatf(
                  {"SMU SV-UVM DTP JTAG smoke (SMU_ALL_005): PTAP IDCODE/BYPASS/TRST+POR on ",
                   "--dut smu_block SEP=0; scenario_seed=%0d random_count=%0d idcode_expect=0x%08h"
                    }, scenario_seed, random_count, expected_idcode), UVM_LOW)
    if (test_cfg.ptap_idcode_negative)
      `uvm_info(get_type_name(), $sformatf(
                "NEGATIVE VALIDATION: arming wrong expected IDCODE 0x%08h instead of 0x%08h",
                expected_idcode,
                SmuPtapIdcode
                ), UVM_LOW)

    run_setup();
    run_idcode(expected_idcode);
    run_bypass();
    run_reset_paths();
    run_timeout_inventory();

    mark_step("PASS", "scenario complete (PASS term recorded for the NONVAC fence)");
    check_evidence(ChkNonvac, "ordered step-delta count", 64'(ordered_step_deltas()),
                   64'(ExpectedStepDeltas), $sformatf("steps=%0d", m_step_order.size()));
    finalize_evidence();
  endtask

  // S1: TAP reset, then Run-Test/Idle confirmed on the DUT observable.
  protected task run_setup();
    bit [15:0] last;
    mark_step("S1", {
              "SETUP: clocks stable; bare tb_top JTAG pins ready for PTAP; ",
              "baseline TAP reset then Run-Test/Idle"
              });
    tap_reset();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s1_rti", 1'b0, last);
    `uvm_info(get_type_name(), $sformatf("BASELINE: jtag_ptap_state=0x%04h (RUN_TEST_IDLE)", last),
              UVM_LOW)
  endtask

  // S2: IDCODE instruction returns the configured device identification.
  protected task run_idcode(bit [31:0] expected_idcode);
    bit [63:0] observed;
    bit [15:0] last;
    mark_step("S2", {
              "ACTION/RESPONSE/EFFECT DTP-JTAG-PTAP.S1: load IDCODE IR; shift 32b DR; ",
              "observe configured IDCODE fields on TDO"
              });
    load_ir(jtag_inst_reg_pkg::IDCODE_INSTR);
    dr_scan(64'h0, IdcodeWidth, observed);
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s2_idcode_rti", 1'b0, last);
    check_evidence(ChkPtapS1, "IDCODE fields", observed[31:0], expected_idcode, $sformatf(
                   "marker=%0b mfr=0x%03h part=0x%04h ver=0x%01h inst_decoded=0x%0h cell=inst=IDCODE",
                   observed[0],
                   observed[11:1],
                   observed[27:12],
                   observed[31:28],
                   dtp_tb_vif.inst_decoded
                   ));
  endtask

  // S3: BYPASS places a single-bit register between TDI and TDO.
  protected task run_bypass();
    bit [31:0] pattern;
    mark_step("S3", {
              "ACTION/RESPONSE/EFFECT DTP-JTAG-PTAP.S2: load BYPASS IR; shift known TDI; ",
              "capture TDO (single-bit register latency)"
              });
    load_ir(jtag_inst_reg_pkg::BYPASS_INSTR);
    shift_bypass_stepwise(BypassPattern);
    for (int unsigned r = 0; r < random_count; r++) begin
      bit [63:0] observed;
      pattern = 32'(random_pattern(BypassWidth));
      log_iteration(r + 1, random_count, $sformatf("BYPASS random pattern tdi=0x%08h", pattern));
      dr_scan(64'(pattern), BypassWidth, observed);
      check_evidence(ChkPtapS2, $sformatf("BYPASS one-bit latency random%0d", r), observed[31:0],
                     ocah_jtag_checker::predict_bypass_tdo(64'(pattern), BypassWidth), $sformatf(
                     "tdi=0x%08h cell=inst=BYPASS", pattern));
    end
  endtask

  // The directed BYPASS scan leg by leg: Select-DR, Capture-DR, Shift-DR,
  // the 32 shift cycles, Update-DR, Run-Test/Idle, each state confirmed.
  protected task shift_bypass_stepwise(bit [31:0] pattern);
    bit          tms_bits[] = new[BypassWidth];
    bit          tdi_bits[] = new[BypassWidth];
    bit          tdo_bits[];
    bit [31:0]   captured = '0;
    bit [15:0] st_cap, st_sh, st_upd, last;
    step(1'b1);  // RTI -> Select-DR
    confirm_state_tck(OCAH_JTAG_SELECT_DR_SCAN, "s3_select_dr", 1'b1, last);
    step(1'b0);  // Select-DR -> Capture-DR
    confirm_state_tck(OCAH_JTAG_CAPTURE_DR, "s3_capture_dr", 1'b0, st_cap);
    step(1'b0);  // Capture-DR -> Shift-DR
    confirm_state_tck(OCAH_JTAG_SHIFT_DR, "s3_shift_dr", 1'b0, st_sh);
    for (int unsigned i = 0; i < BypassWidth; i++) begin
      tdi_bits[i] = pattern[i];
      tms_bits[i] = (i == BypassWidth - 1);  // last shift exits to Exit1-DR
    end
    raw_walk(tms_bits, tdi_bits, tdo_bits);
    foreach (tdo_bits[i]) captured[i] = tdo_bits[i];
    step(1'b1);  // Exit1-DR -> Update-DR
    confirm_state_tck(OCAH_JTAG_UPDATE_DR, "s3_update_dr", 1'b1, st_upd);
    step(1'b0);  // Update-DR -> RTI
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s3_back_rti", 1'b0, last);
    check_evidence(ChkPtapS2, "BYPASS one-bit latency", captured,
                   ocah_jtag_checker::predict_bypass_tdo(64'(pattern), BypassWidth), $sformatf(
                   "tdi=0x%08h cap=0x%04h sh=0x%04h upd=0x%04h cell=inst=BYPASS",
                   pattern,
                   st_cap,
                   st_sh,
                   st_upd
                   ));
  endtask

  // S4: TRST, then power-on reset, each from Shift-DR back to
  // Test-Logic-Reset.
  protected task run_reset_paths();
    bit [15:0] pre_trst, tlr_trst, pre_por, tlr_por;
    mark_step("S4", {
              "ACTION/RESPONSE/EFFECT DTP-JTAG-PTAP.S3: from non-TLR, TRST pulse then ",
              "POR (powergood) each return TAP to Test-Logic-Reset"
              });

    enter_shift_dr_under_bypass();
    pre_trst = tap_state();
    if (pre_trst === onehot(OCAH_JTAG_TEST_LOGIC_RESET))
      `uvm_error(get_type_name(), "pre-TRST already Test-Logic-Reset; cannot prove the TRST effect")
    set_trst(1'b0, test_cfg.trst_hold_tck_cycles);
    wait_tap_eq_ref(OCAH_JTAG_TEST_LOGIC_RESET, "s4_trst_tlr", tlr_trst);
    release_trst();

    enter_shift_dr_under_bypass();
    pre_por = tap_state();
    if (pre_por === onehot(OCAH_JTAG_TEST_LOGIC_RESET))
      `uvm_error(get_type_name(), "pre-POR already Test-Logic-Reset; cannot prove the POR effect")
    if (!trst_released()) `uvm_error(get_type_name(), "POR path requires TRST released")
    drop_powergood();
    wait_tap_eq_ref(OCAH_JTAG_TEST_LOGIC_RESET, "s4_por_tlr", tlr_por);
    restore_powergood();

    check_evidence(ChkPtapS3, "TRST -> TLR", tlr_trst, onehot(OCAH_JTAG_TEST_LOGIC_RESET),
                   $sformatf("pre_trst=0x%04h cells=rst=TRST,state=Test-Logic-Reset", pre_trst));
    check_evidence(ChkPtapS3, "POR -> TLR", tlr_por, onehot(OCAH_JTAG_TEST_LOGIC_RESET), $sformatf(
                   "pre_por=0x%04h cells=rst=POR,state=Test-Logic-Reset", pre_por));
  endtask

  // Leave Test-Logic-Reset, load BYPASS, and park in Shift-DR.
  protected task enter_shift_dr_under_bypass();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    load_ir(jtag_inst_reg_pkg::BYPASS_INSTR);
    goto_state(OCAH_JTAG_SHIFT_DR);
  endtask

  // S5: every bounded wait named a finite bound and its last state, none
  // expired, and the site count equals the cocotb scenario's.
  protected task run_timeout_inventory();
    mark_step("S5",
              "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last TAP state");
    log_timeout_paths();
    check_evidence(ChkTimeoutPaths, "bounded wait sites", 64'(timeout_path_count()),
                   64'(ExpectedTimeoutPaths), $sformatf(
                   "expired=%0d bound_tck=%0d bound_ref=%0d",
                   timeouts_expired(),
                   test_cfg.bound_tck,
                   test_cfg.bound_ref
                   ));
    check_evidence(ChkTimeoutPaths, "expired wait sites", 64'(timeouts_expired()), 64'd0);
  endtask

endclass : smu_dtp_jtag_smoke_test_seq
