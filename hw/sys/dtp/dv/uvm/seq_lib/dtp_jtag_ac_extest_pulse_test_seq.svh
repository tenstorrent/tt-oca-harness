// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AC EXTEST_PULSE scan-loopback scenario. EXTEST_PULSE (IR 0x06) selects the
// boundary-scan chain, which this bench loops back without boundary cells.
// The chain's run_test_idle strobe is the Run-Test/Idle decode the AC pulse
// launches on: one pulse across a DR scan, on the return to Run-Test/Idle,
// and high while the TAP is parked there (CHK-BSR-RTI). Mirrors the cocotb
// dtp_jtag_ac_extest_pulse_test_seq.

class dtp_jtag_ac_extest_pulse_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_ac_extest_pulse_test_seq)
  localparam string RtiCheckId = "CHK-BSR-RTI";
  localparam string RtiSignal = "jtag_bsr_run_test_idle";

  function new(string name = "dtp_jtag_ac_extest_pulse_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-BSR-SELECT", "CHK-BSR-SCAN-CTRL", "CHK-BSR-RTI",
                              "CHK-BYPASS-DELAY", "CHK-SCAN-COUNT", "CHK-SCAN-IR-LEN",
                              "CHK-SCAN-DR-LEN", "CHK-NONVAC"};
    string extra[$] = {RtiSignal};
    int unsigned counts[string];
    bit [63:0] walking_patterns[$] = {64'h01, 64'h02, 64'h04, 64'h08,
                                          64'h10, 64'h20, 64'h40, 64'h80};
    bit [63:0] edge_patterns[$] = {64'hAA, 64'h55, 64'hFF, 64'h00};
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();
    check_loopback_scan(6'(EXTEST_TRAIN_INSTR), 64'h33);
    check_loopback_patterns(6'(EXTEST_PULSE_INSTR));
    foreach (walking_patterns[p]) check_loopback_scan(6'(EXTEST_PULSE_INSTR), walking_patterns[p]);
    foreach (edge_patterns[p]) check_loopback_scan(6'(EXTEST_PULSE_INSTR), edge_patterns[p]);
    `uvm_info(get_type_name(),
              "Step 3: EXTEST_PULSE scan controls; run_test_idle pulses once, on the return",
              UVM_LOW)
    check_bsr_scan_ctrl_counts(6'(EXTEST_PULSE_INSTR), random_pattern(DtpBsrModelLen),
                               DtpBsrModelLen, DTP_SCAN_CTRL_SELECTED, extra, counts);
    family_check(RtiCheckId, {RtiSignal, " pulses across the scan"}, 64'(counts[RtiSignal]), 64'd1,
                 "EXTEST_PULSE DR scan");
    `uvm_info(get_type_name(), "Step 4: EXTEST_PULSE parked in Run-Test/Idle holds run_test_idle high",
              UVM_LOW)
    check_scan_observable(RtiCheckId, RtiSignal, 1'b1, "EXTEST_PULSE parked in Run-Test/Idle");
    check_scan_observable(RtiCheckId, "jtag_bsr_select", 1'b0,
                          "EXTEST_PULSE parked in Run-Test/Idle");
    `uvm_info(get_type_name(), "Step 5: BYPASS scan: select stays low while the TAP strobes pulse",
              UVM_LOW)
    check_bsr_scan_ctrl(6'(BYPASS_INSTR), 64'h3C3C, 16, DTP_SCAN_CTRL_UNSELECTED);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_ac_extest_pulse_test_seq
