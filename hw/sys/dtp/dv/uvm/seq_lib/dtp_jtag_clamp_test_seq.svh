// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CLAMP chain-deselect and bypass-path scenario: EXTEST selects the
// looped-back chain under a scan-control window, CLAMP scans leave the
// select low while the TAP strobes pulse and scan the one-bit bypass across
// the directed/random pattern classes, EXTEST selects the chain again, and a
// BYPASS delay check closes. Mirrors the cocotb dtp_jtag_clamp_test_seq.

class dtp_jtag_clamp_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_clamp_test_seq)

  function new(string name = "dtp_jtag_clamp_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR",
                          "CHK-IR-DECODE",
                          "CHK-BSR-LOOPBACK",
                          "CHK-BSR-SELECT",
                          "CHK-BSR-SCAN-CTRL",
                          "CHK-BYPASS-DELAY",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"};
    seed_scenario_rng();
    attach_family_checker(required);
    reset_to_tlr();
    log_step("1", "EXTEST selects the looped-back chain and lands a pattern");
    check_bsr_scan_ctrl(6'(EXTEST_INSTR), random_pattern(DtpBsrModelLen));
    log_step("2", "CLAMP leaves the chain deselected while the TAP strobes pulse");
    check_bsr_scan_ctrl(6'(CLAMP_INSTR), 64'hA5A5, 16, DTP_SCAN_CTRL_UNSELECTED);
    check_bypass_patterns(6'(CLAMP_INSTR), 64);
    log_step("3", "EXTEST after CLAMP selects the chain again");
    check_bsr_scan_ctrl(6'(EXTEST_INSTR), random_pattern(DtpBsrModelLen));
    check_bypass_delay(6'(BYPASS_INSTR), 64'h5A5A_A5A5);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_clamp_test_seq
