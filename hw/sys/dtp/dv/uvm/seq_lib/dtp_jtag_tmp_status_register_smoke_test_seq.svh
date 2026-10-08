// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// TMP_STATUS register smoke scenario: persistence (bit 1) must read 0
// after TAP reset and across a shuffled 2-bit shift-value sweep (bit 1 is
// read-only until CLAMP_HOLD), CLAMP_HOLD must drive Persistence-On, and a
// final IDCODE read returns the configured IDCODE.
// Mirrors the cocotb dtp_jtag_tmp_status_register_smoke_test_seq.

class dtp_jtag_tmp_status_register_smoke_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_tmp_status_register_smoke_test_seq)

  function new(string name = "dtp_jtag_tmp_status_register_smoke_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST", "CHK-DBG-TDR"};
    bit [1:0] shift_values[4] = '{2'b00, 2'b01, 2'b10, 2'b11};
    bit persistence, bypass_escape;
    bit [63:0] idcode;
    seed_scenario_rng();
    attach_family_checker(required);

    log_step("1", "Reset TAP and confirm TMP starts Persistence-Off");
    reset_to_tlr();
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                 "after reset");

    // Shuffled shift-value sweep: bit 1 stays 0 until CLAMP_HOLD
    // regardless of the shifted-in image (seeded per-pass order).
    log_step("2", "Read TMP_STATUS with several DR shift values");
    shift_values.shuffle();
    foreach (shift_values[idx]) begin
      log_iteration(idx + 1, 4, $sformatf("TMP_STATUS shift_value=0b%02b", shift_values[idx]));
      read_tmp_status(persistence, bypass_escape, shift_values[idx]);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0, $sformatf(
                   "shift_value=0b%02b", shift_values[idx]));
    end

    log_step("3", "Apply CLAMP_HOLD and expect Persistence-On");
    load_ir(6'(CLAMP_HOLD_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                 "after CLAMP_HOLD");

    log_step("4", "Read IDCODE and expect the configured IDCODE after TMP_STATUS access");
    check_idcode_value(idcode, "after TMP_STATUS");

    finalize_family_checker();
  endtask

endclass : dtp_jtag_tmp_status_register_smoke_test_seq
