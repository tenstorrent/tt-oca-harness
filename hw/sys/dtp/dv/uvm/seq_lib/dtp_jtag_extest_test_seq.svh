// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// EXTEST scan-loopback scenario: SAMPLE/PRELOAD preload, directed/random
// EXTEST loopback patterns, a BYPASS 1-TCK delay check, and a final EXTEST
// loopback. Mirrors the cocotb dtp_jtag_extest_test_seq.

class dtp_jtag_extest_test_seq extends dtp_jtag_cmd_lib_seq;
  `uvm_object_utils(dtp_jtag_extest_test_seq)

  function new(string name = "dtp_jtag_extest_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR",
                          "CHK-IR-DECODE",
                          "CHK-BSR-LOOPBACK",
                          "CHK-BYPASS-DELAY",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"};
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();
    check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), 64'h3C);
    check_loopback_patterns(6'(EXTEST_INSTR));
    check_bypass_delay(6'(BYPASS_INSTR), 64'hA5A5);
    check_loopback_scan(6'(EXTEST_INSTR), 64'hC3);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_extest_test_seq
