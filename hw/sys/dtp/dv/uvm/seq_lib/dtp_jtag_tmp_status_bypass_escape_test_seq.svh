// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// TMP BYPASS_ESCAPE scenario: CLAMP_HOLD drives Persistence-On, writing
// TMP_STATUS bit 0 arms the escape (retained across readbacks that also
// read persistence 1), selecting BYPASS twice triggers the escape
// transition (the TMP controller samples bypass_selected during Update-IR),
// and the recovered BYPASS path shifts a seeded pattern with the 1-TCK
// latency contract. An arm write followed by a TAP reset then reads back
// 0b00. Mirrors the cocotb dtp_jtag_tmp_status_bypass_escape_test_seq.

class dtp_jtag_tmp_status_bypass_escape_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_tmp_status_bypass_escape_test_seq)

  function new(string name = "dtp_jtag_tmp_status_bypass_escape_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST",
                              "CHK-TMP-ESCAPE", "CHK-BYPASS-DELAY"};
    bit [1:0] armed_shifts[2] = '{2'b01, 2'b11};
    bit persistence, bypass_escape;
    bit [63:0] bypass_pattern;
    seed_scenario_rng();
    attach_family_checker(required);

    log_step("1", "Reset TAP and establish Persistence-On through CLAMP_HOLD");
    reset_to_tlr();
    load_ir(6'(CLAMP_HOLD_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                 "after CLAMP_HOLD");

    log_step("2", "Arm BYPASS_ESCAPE and verify bit 0 is retained with persistence on");
    write_tmp_status(2'b01);
    // Both preserve values keep bit 0 armed; the seeded per-pass order
    // varies which one the BYPASS loads follow.
    if ($urandom_range(1)) armed_shifts = '{2'b11, 2'b01};
    foreach (armed_shifts[idx]) begin
      log_iteration(idx + 1, 2, $sformatf("armed readback shift_value=0b%02b", armed_shifts[idx]));
      check_tmp_status(1'b1, 1'b1, armed_shifts[idx], $sformatf(
                       "armed shift_value=0b%02b", armed_shifts[idx]));
    end

    // The TMP controller samples bypass_selected during Update-IR: load
    // BYPASS twice so the second Update-IR observes BYPASS selected.
    log_step("3", "Select BYPASS twice to trigger the escape transition");
    load_ir(6'(BYPASS_INSTR));
    load_ir(6'(BYPASS_INSTR));

    log_step("4", "Verify Persistence-Off after BYPASS escape");
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                 "after BYPASS escape");

    log_step("5", "Check normal BYPASS scan routing after escape");
    bypass_pattern = 64'($urandom) & bit_mask(16);
    check_bypass_delay(6'(BYPASS_INSTR), bypass_pattern, 16);

    // With persistence off the arm has no effect. Capture-DR returns the reset
    // register, 0b00, not the 0b01 last shifted in.
    log_step("6", "Arm BYPASS_ESCAPE, reset the TAP, and read TMP_STATUS");
    write_tmp_status(2'b01);
    reset_to_tlr();
    check_tmp_status(1'b0, 1'b0, 2'b00, "after TAP reset, armed before the reset");

    finalize_family_checker();
  endtask

endclass : dtp_jtag_tmp_status_bypass_escape_test_seq
