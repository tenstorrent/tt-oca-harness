// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CLAMP_HOLD TMP persistence scenario. CLAMP_HOLD (IR 0x0A) is a TMP
// instruction: its Update-IR turns test-mode persistence on, its data
// register is the one-bit bypass (CHK-BYPASS-DELAY), and TMP_STATUS bit 1
// reads the persistence back (CHK-TMP-PERSIST). For each directed/random
// preload pattern the persistence must survive an instruction switch to
// BYPASS and CLAMP_RELEASE must clear it; a final TAP reset must leave it
// clear. Mirrors the cocotb dtp_jtag_clamp_hold_test_seq.

class dtp_jtag_clamp_hold_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_clamp_hold_test_seq)

  function new(string name = "dtp_jtag_clamp_hold_test_seq");
    super.new(name);
  endfunction

  // Read TMP_STATUS and record its persistence bit.
  protected task check_persistence(string label, bit expected);
    bit persistence, bypass_escape;
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'(expected),
                 label);
  endtask

  // Preload, then CLAMP_HOLD sets persistence, BYPASS keeps it, CLAMP_RELEASE
  // clears it.
  protected task check_clamp_hold_cycle(bit [63:0] pattern);
    check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), pattern, DtpBsrModelLen);
    check_bypass_delay(6'(CLAMP_HOLD_INSTR), random_pattern(64));
    check_persistence("CLAMP_HOLD", 1'b1);
    load_ir(6'(BYPASS_INSTR));
    check_persistence("instruction switch", 1'b1);
    load_ir(6'(CLAMP_RELEASE_INSTR));
    check_persistence("CLAMP_RELEASE", 1'b0);
  endtask

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-BYPASS-DELAY", "CHK-TMP-PERSIST"};
    bit [63:0] patterns[$];
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();

    directed_patterns(DtpBsrModelLen, patterns);
    foreach (patterns[p]) begin
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: SAMPLE_PRELOAD pattern=0x%02h", p + 1, patterns.size(), patterns[p]),
          UVM_LOW)
      check_clamp_hold_cycle(patterns[p]);
    end

    // TAP reset must leave TMP persistence clear.
    reset_to_tlr();
    check_persistence("TAP reset", 1'b0);

    finalize_family_checker();
  endtask

endclass : dtp_jtag_clamp_hold_test_seq
