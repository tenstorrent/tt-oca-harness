// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AC EXTEST_PULSE scan-loopback scenario: EXTEST_TRAIN preload,
// directed/random EXTEST_PULSE loopback patterns, a walking-one sweep, and
// alternating/edge patterns. Mirrors the cocotb
// dtp_jtag_ac_extest_pulse_test_seq.

class dtp_jtag_ac_extest_pulse_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_ac_extest_pulse_test_seq)

  function new(string name = "dtp_jtag_ac_extest_pulse_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-SCAN-COUNT", "CHK-SCAN-IR-LEN", "CHK-SCAN-DR-LEN",
                              "CHK-NONVAC"};
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
    finalize_family_checker();
  endtask

endclass : dtp_jtag_ac_extest_pulse_test_seq
