// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CLAMP_RELEASE TMP persistence scenario: release without a prior hold is
// harmless; for each directed/random preload pattern a CLAMP_HOLD sets TMP
// persistence, the persistence survives a BYPASS switch, and CLAMP_RELEASE
// clears it; a repeated release keeps persistence clear. Mirrors the cocotb
// dtp_jtag_clamp_release_test_seq.

class dtp_jtag_clamp_release_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_clamp_release_test_seq)

  function new(string name = "dtp_jtag_clamp_release_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-TMP-PERSIST"};
    bit [63:0] patterns[$];
    bit persistence, bypass_escape;
    seed_scenario_rng();
    attach_family_checker(required);

    // Release without a prior hold must be harmless.
    reset_to_tlr();
    load_ir(6'(CLAMP_RELEASE_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                 "initial release");

    directed_patterns(DtpBsrModelLen, patterns);
    foreach (patterns[p]) begin
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: SAMPLE_PRELOAD pattern=0x%02h", p + 1, patterns.size(), patterns[p]),
          UVM_LOW)
      check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), patterns[p], DtpBsrModelLen);

      load_ir(6'(CLAMP_HOLD_INSTR));
      read_tmp_status(persistence, bypass_escape);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                   "hold setup");

      load_ir(6'(BYPASS_INSTR));
      read_tmp_status(persistence, bypass_escape);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                   "pre-release switch");

      load_ir(6'(CLAMP_RELEASE_INSTR));
      expect_decoded_instruction(CLAMP_RELEASE_INSTR);
      read_tmp_status(persistence, bypass_escape);
      family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                   "release clear");
    end

    // Repeated release keeps persistence clear.
    load_ir(6'(CLAMP_RELEASE_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                 "repeated release");

    finalize_family_checker();
  endtask

endclass : dtp_jtag_clamp_release_test_seq
