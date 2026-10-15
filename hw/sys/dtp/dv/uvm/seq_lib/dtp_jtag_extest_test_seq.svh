// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// EXTEST scan-loopback scenario. EXTEST (IR 0x04) selects the boundary-scan
// chain; this bench has no boundary cells, so the looped-back chain returns
// the pattern one TCK late and the boundary-scan select rides the TAP's
// capture/shift/update strobes across the scan (CHK-BSR-SELECT,
// CHK-BSR-SCAN-CTRL). Under BYPASS the select stays low while the same
// strobes pulse. Mirrors the cocotb dtp_jtag_extest_test_seq.

class dtp_jtag_extest_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_extest_test_seq)

  function new(string name = "dtp_jtag_extest_test_seq");
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
    log_step("1", "SAMPLE/PRELOAD preload through the looped-back chain");
    check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), 64'h3C);
    log_step("2", "EXTEST loopback across directed and seeded patterns");
    check_loopback_patterns(6'(EXTEST_INSTR));
    log_step("3", "EXTEST scan controls: select high, one capture, N shifts, one update");
    check_bsr_scan_ctrl(6'(EXTEST_INSTR), random_pattern(DtpBsrModelLen));
    log_step("4", "BYPASS scan: select stays low while the TAP strobes pulse");
    check_bsr_scan_ctrl(6'(BYPASS_INSTR), 64'hA5A5, 16, DTP_SCAN_CTRL_UNSELECTED);
    check_loopback_scan(6'(EXTEST_INSTR), 64'hC3);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_extest_test_seq
