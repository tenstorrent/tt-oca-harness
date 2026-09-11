// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AC EXTEST_TRAIN scan-loopback scenario: SAMPLE/PRELOAD zero preload,
// directed/random EXTEST_TRAIN loopback patterns, four directed train
// patterns, and a final EXTEST loopback. Mirrors the cocotb
// dtp_jtag_ac_extest_train_test_seq.

class dtp_jtag_ac_extest_train_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_ac_extest_train_test_seq)

  function new(string name = "dtp_jtag_ac_extest_train_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-SCAN-COUNT", "CHK-SCAN-IR-LEN", "CHK-SCAN-DR-LEN",
                              "CHK-NONVAC"};
    bit [63:0] train_patterns[$] = {64'h0F, 64'hF0, 64'h33, 64'hCC};
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();
    check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), 64'h00);
    check_loopback_patterns(6'(EXTEST_TRAIN_INSTR));
    foreach (train_patterns[p]) check_loopback_scan(6'(EXTEST_TRAIN_INSTR), train_patterns[p]);
    check_loopback_scan(6'(EXTEST_INSTR), 64'hA5);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_ac_extest_train_test_seq
