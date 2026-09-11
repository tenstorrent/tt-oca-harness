// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// TMP BYPASS_ESCAPE scenario: CLAMP_HOLD drives Persistence-On, writing
// TMP_STATUS bit 0 arms the escape (retained across readbacks), selecting
// BYPASS twice triggers the escape transition (the TMP controller samples
// bypass_selected during Update-IR), and the recovered BYPASS path shifts
// a seeded pattern with the 1-TCK latency contract. Mirrors the cocotb
// dtp_jtag_tmp_status_bypass_escape_test_seq.

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

    reset_to_tlr();
    load_ir(6'(CLAMP_HOLD_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                 "after CLAMP_HOLD");

    write_tmp_status(2'b01);
    foreach (armed_shifts[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/2: armed readback shift_value=0b%02b", idx + 1, armed_shifts[idx]),
                UVM_LOW)
      read_tmp_status(persistence, bypass_escape, armed_shifts[idx]);
      family_check("CHK-TMP-ESCAPE", "TMP_STATUS.bypass_escape", 64'(bypass_escape), 64'd1,
                   $sformatf("shift_value=0b%02b", armed_shifts[idx]));
    end

    // The TMP controller samples bypass_selected during Update-IR: load
    // BYPASS twice so the second Update-IR observes BYPASS selected.
    load_ir(6'(BYPASS_INSTR));
    load_ir(6'(BYPASS_INSTR));

    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                 "after BYPASS escape");

    // Seeded per-pass pattern through the recovered BYPASS path.
    bypass_pattern = 64'($urandom) & bit_mask(16);
    check_bypass_delay(6'(BYPASS_INSTR), bypass_pattern, 16);

    finalize_family_checker();
  endtask

endclass : dtp_jtag_tmp_status_bypass_escape_test_seq
