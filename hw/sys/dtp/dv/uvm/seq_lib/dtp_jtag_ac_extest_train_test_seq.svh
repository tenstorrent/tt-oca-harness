// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AC EXTEST_TRAIN scan-loopback scenario. EXTEST_TRAIN (IR 0x05) selects the
// boundary-scan chain, which this bench loops back without boundary cells.
// The chain's run_test_idle strobe is the Run-Test/Idle decode the AC
// training launches on: high while the TAP is parked in Run-Test/Idle, low
// in Test-Logic-Reset, and one pulse across a DR scan, on the return to
// Run-Test/Idle (CHK-BSR-RTI). Mirrors the cocotb
// dtp_jtag_ac_extest_train_test_seq.

class dtp_jtag_ac_extest_train_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_ac_extest_train_test_seq)

  localparam string RtiCheckId = "CHK-BSR-RTI";
  localparam string RtiSignal = "jtag_bsr_run_test_idle";
  localparam string TlrSignal = "jtag_bsr_test_logic_reset";

  function new(string name = "dtp_jtag_ac_extest_train_test_seq");
    super.new(name);
  endfunction

  // EXTEST_TRAIN parked in Run-Test/Idle raises run_test_idle;
  // Test-Logic-Reset drops it.
  protected task check_run_test_idle_strobe();
    load_ir(6'(EXTEST_TRAIN_INSTR));
    expect_decoded_instruction(EXTEST_TRAIN_INSTR);
    check_scan_observable(RtiCheckId, RtiSignal, 1'b1, "EXTEST_TRAIN parked in Run-Test/Idle");
    check_scan_observable(RtiCheckId, TlrSignal, 1'b0, "EXTEST_TRAIN parked in Run-Test/Idle");
    check_scan_observable(RtiCheckId, "jtag_bsr_select", 1'b0,
                          "EXTEST_TRAIN parked in Run-Test/Idle");
    goto_state(OCAH_JTAG_TEST_LOGIC_RESET);
    check_state(TEST_LOGIC_RESET, "jtag_train_chk", "parked in Test-Logic-Reset");
    check_scan_observable(RtiCheckId, RtiSignal, 1'b0, "parked in Test-Logic-Reset");
    check_scan_observable(RtiCheckId, TlrSignal, 1'b1, "parked in Test-Logic-Reset");
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag_train_chk", "after TLR->RTI step");
  endtask

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR",
                          "CHK-IR-DECODE",
                          "CHK-BSR-LOOPBACK",
                          "CHK-BSR-SELECT",
                          "CHK-BSR-SCAN-CTRL",
                          "CHK-BSR-RTI",
                          "CHK-BYPASS-DELAY",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"};
    bit [63:0] train_patterns[$] = {64'h0F, 64'hF0, 64'h33, 64'hCC};
    string extra[$] = {RtiSignal};
    int unsigned counts[string];
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();
    `uvm_info(get_type_name(), "Step 1: SAMPLE/PRELOAD zero preload through the looped-back chain",
              UVM_LOW)
    check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), 64'h00);
    `uvm_info(get_type_name(),
              "Step 2: EXTEST_TRAIN loopback across directed, train, and seeded patterns", UVM_LOW)
    check_loopback_patterns(6'(EXTEST_TRAIN_INSTR));
    foreach (train_patterns[p]) check_loopback_scan(6'(EXTEST_TRAIN_INSTR), train_patterns[p]);
    `uvm_info(get_type_name(), "Step 3: run_test_idle strobe follows the TAP parking state",
              UVM_LOW)
    check_run_test_idle_strobe();
    `uvm_info(get_type_name(),
              "Step 4: EXTEST_TRAIN scan controls; run_test_idle pulses once, on the return",
              UVM_LOW)
    check_bsr_scan_ctrl_counts(6'(EXTEST_TRAIN_INSTR), random_pattern(DtpBsrModelLen),
                               DtpBsrModelLen, DTP_SCAN_CTRL_SELECTED, extra, counts);
    family_check(RtiCheckId, {RtiSignal, " pulses across the scan"}, 64'(counts[RtiSignal]), 64'd1,
                 "EXTEST_TRAIN DR scan");
    `uvm_info(get_type_name(), "Step 5: BYPASS scan: select stays low while the TAP strobes pulse",
              UVM_LOW)
    check_bsr_scan_ctrl(6'(BYPASS_INSTR), 64'h3C3C, 16, DTP_SCAN_CTRL_UNSELECTED);
    check_loopback_scan(6'(EXTEST_INSTR), 64'hA5);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_ac_extest_train_test_seq
