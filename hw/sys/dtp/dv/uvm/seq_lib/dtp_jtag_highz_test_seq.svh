// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// HIGHZ instruction scenario. HIGHZ (IR 0x08) decodes as its own instruction
// but scans the one-bit bypass register and leaves the boundary-scan select
// low while the TAP's strobes pulse; this bench has no boundary output
// enables to observe. A boundary-scan instruction loaded afterwards
// re-selects the looped-back chain. Mirrors the cocotb
// dtp_jtag_highz_test_seq.

class dtp_jtag_highz_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_highz_test_seq)

  function new(string name = "dtp_jtag_highz_test_seq");
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
    log_step("1", "EXTEST loopback before HIGHZ");
    check_loopback_scan(6'(EXTEST_INSTR), 64'h0F);
    log_step("2", "HIGHZ decodes and scans the one-bit bypass across the pattern classes");
    check_bypass_patterns(6'(HIGHZ_INSTR), 64);
    log_step("3", "HIGHZ scan: boundary-scan select low, TAP strobes pulsing, bypass TDO");
    check_bsr_scan_ctrl(6'(HIGHZ_INSTR), random_pattern(64), 64, DTP_SCAN_CTRL_UNSELECTED);
    log_step("4", "EXTEST after HIGHZ re-selects the looped-back chain");
    check_bsr_scan_ctrl(6'(EXTEST_INSTR), random_pattern(DtpBsrModelLen));
    check_bypass_delay(6'(CLAMP_INSTR), 64'h0F0F_F0F0);
    load_ir(6'(IDCODE_INSTR));
    check_bypass_delay(6'(HIGHZ_INSTR), 64'h5A5A_5A5A_5A5A_5A5A);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_highz_test_seq
