// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SAMPLE/PRELOAD scan-loopback scenario. SAMPLE/PRELOAD (IR 0x03) selects
// the boundary-scan chain; this bench has no boundary cells, so the
// looped-back chain returns the pattern one TCK late and the boundary-scan
// select rides the TAP's capture/shift/update strobes across the scan
// (CHK-BSR-SELECT, CHK-BSR-SCAN-CTRL). Under BYPASS the select stays low
// while the same strobes pulse. Mirrors the cocotb
// dtp_jtag_sample_preload_test_seq.

class dtp_jtag_sample_preload_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_sample_preload_test_seq)

  function new(string name = "dtp_jtag_sample_preload_test_seq");
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
    `uvm_info(get_type_name(),
              "Step 1: SAMPLE/PRELOAD loopback across directed and seeded patterns", UVM_LOW)
    check_loopback_patterns(6'(SAMPLE_PRELOAD_INSTR));
    `uvm_info(
        get_type_name(),
        "Step 2: SAMPLE/PRELOAD scan controls: select high, one capture, N shifts, one update",
        UVM_LOW)
    check_bsr_scan_ctrl(6'(SAMPLE_PRELOAD_INSTR), random_pattern(DtpBsrModelLen));
    `uvm_info(get_type_name(), "Step 3: BYPASS scan: select stays low while the TAP strobes pulse",
              UVM_LOW)
    check_bsr_scan_ctrl(6'(BYPASS_INSTR), 64'h5A5A, 16, DTP_SCAN_CTRL_UNSELECTED);
    check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), 64'h3C);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_sample_preload_test_seq
