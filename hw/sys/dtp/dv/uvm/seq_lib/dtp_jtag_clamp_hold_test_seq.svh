// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CLAMP_HOLD TMP persistence scenario: for each directed/random preload
// pattern, CLAMP_HOLD must set TMP persistence (TMP_STATUS bit 1), the
// persistence must survive an instruction switch to BYPASS, and
// CLAMP_RELEASE must clear it; a final TAP reset must leave persistence
// clear. Mirrors the cocotb dtp_jtag_clamp_hold_test_seq.

class dtp_jtag_clamp_hold_test_seq extends dtp_jtag_cmd_lib_seq;
  `uvm_object_utils(dtp_jtag_clamp_hold_test_seq)

  function new(string name = "dtp_jtag_clamp_hold_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-TMP-PERSIST"};
    bit [63:0] patterns[$];
    bit persistence, bypass_escape;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();

    directed_patterns(DtpBsrModelLen, patterns);
    foreach (patterns[p]) begin
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: SAMPLE_PRELOAD pattern=0x%02h", p + 1, patterns.size(), patterns[p]),
          UVM_LOW)
      check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), patterns[p], DtpBsrModelLen);

      load_ir(6'(CLAMP_HOLD_INSTR));
      expect_decoded_instruction(CLAMP_HOLD_INSTR);
      read_tmp_status(persistence, bypass_escape);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                   "CLAMP_HOLD");

      load_ir(6'(BYPASS_INSTR));
      read_tmp_status(persistence, bypass_escape);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                   "instruction switch");

      load_ir(6'(CLAMP_RELEASE_INSTR));
      read_tmp_status(persistence, bypass_escape);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                   "CLAMP_RELEASE");
    end

    // TAP reset must leave TMP persistence clear.
    reset_to_tlr();
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0, "TAP reset");

    finalize_family_checker();
  endtask

endclass : dtp_jtag_clamp_hold_test_seq
