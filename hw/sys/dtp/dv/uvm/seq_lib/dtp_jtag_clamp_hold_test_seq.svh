// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CLAMP_HOLD TMP persistence scenario. CLAMP_HOLD (IR 0x0A) is a TMP
// instruction: its Update-IR turns test-mode persistence on, its data
// register is the one-bit bypass (CHK-BYPASS-DELAY), and TMP_STATUS bit 1
// reads the persistence back (CHK-TMP-PERSIST). For each directed/random
// preload pattern the persistence must be off before CLAMP_HOLD, survive an
// instruction switch to BYPASS, and clear on CLAMP_RELEASE; after the sweep
// CLAMP_HOLD's persistence must survive five TMS-high clocks into
// Test-Logic-Reset and clear on a TRST reset. Mirrors the cocotb
// dtp_jtag_clamp_hold_test_seq.

class dtp_jtag_clamp_hold_test_seq extends dtp_debug_tdr_base_test_seq;
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
    check_persistence("before CLAMP_HOLD", 1'b0);
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

    log_step("1", "Reset TAP before CLAMP_HOLD sweep");
    reset_to_tlr();

    directed_patterns(DtpBsrModelLen, patterns);
    log_step("2", "Loop through scan patterns and verify TMP persistence");
    foreach (patterns[p]) begin
      log_iteration(p + 1, patterns.size(), $sformatf("SAMPLE_PRELOAD pattern=0x%02h", patterns[p]
                    ));
      check_clamp_hold_cycle(patterns[p]);
    end

    log_step("3", "Persistence survives a TMS-driven Test-Logic-Reset; a TRST reset clears it");
    load_ir(6'(CLAMP_HOLD_INSTR));
    check_persistence("CLAMP_HOLD before Test-Logic-Reset", 1'b1);
    goto_tlr_via_tms();
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag_clamp_hold_chk", "after TLR->RTI step");
    check_persistence("after five TMS-high clocks", 1'b1);
    reset_to_tlr();
    check_persistence("TRST from Persistence-On", 1'b0);

    finalize_family_checker();
  endtask

endclass : dtp_jtag_clamp_hold_test_seq
