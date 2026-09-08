// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// HIGHZ instruction bypass-path scenario: EXTEST loopback preload, HIGHZ
// one-bit bypass behavior across the directed/random pattern classes, a
// CLAMP delay check, IR churn through IDCODE, and a final HIGHZ delay
// check. Mirrors the cocotb dtp_jtag_highz_test_seq.

class dtp_jtag_highz_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_highz_test_seq)

  function new(string name = "dtp_jtag_highz_test_seq");
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
    check_loopback_scan(6'(EXTEST_INSTR), 64'h0F);
    check_bypass_patterns(6'(HIGHZ_INSTR), 64);
    check_bypass_delay(6'(CLAMP_INSTR), 64'h0F0F_F0F0);
    load_ir(6'(IDCODE_INSTR));
    check_bypass_delay(6'(HIGHZ_INSTR), 64'h5A5A_5A5A_5A5A_5A5A);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_highz_test_seq
