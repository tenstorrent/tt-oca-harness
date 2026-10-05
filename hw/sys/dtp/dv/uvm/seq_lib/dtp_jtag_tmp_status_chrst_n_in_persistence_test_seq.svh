// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// TMP persistence across the system reset and Test-Logic-Reset: CLAMP_HOLD
// drives Persistence-On, a seeded-width rst_n_i pulse (POR and TRST
// untouched) must not clear it, and a TMS-driven Test-Logic-Reset keeps it
// and leaves the boundary-scan host control's chrst_n released; once
// CLAMP_RELEASE ends persistence, Test-Logic-Reset asserts chrst_n. A final
// IDCODE read returns the configured IDCODE. Mirrors the cocotb
// dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq.

class dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq)

  function new(string name = "dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq");
    super.new(name);
  endfunction

  // Walk to Test-Logic-Reset without TRST, record chrst_n there
  // (CHK-TMP-CHRST), and return to Run-Test/Idle.
  protected task check_chrst_n_in_tlr(bit expected, string context_s);
    goto_tlr_via_tms();
    check_scan_observable("CHK-TMP-CHRST", "jtag_bsr_test_logic_reset", 1'b1, context_s);
    check_scan_observable("CHK-TMP-CHRST", "jtag_bsr_chrst_n", expected, context_s);
    step(1'b0);
    check_state(RUN_TEST_IDLE, "debug_tdr_scan_chk", "after TMS TLR->RTI");
  endtask

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST", "CHK-TMP-CHRST", "CHK-DBG-TDR"};
    bit persistence, bypass_escape;
    bit [63:0] idcode;
    int unsigned reset_cycles;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();
    load_ir(6'(CLAMP_HOLD_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                 "before system reset");

    // Seeded per-pass pulse width in clk_i cycles; TCK is idle during the
    // pulse.
    reset_cycles = $urandom_range(12, 3);
    `uvm_info(get_type_name(), $sformatf("Pulse rst_n_i for %0d cycles with TAP held accessible",
                                         reset_cycles), UVM_LOW)
    pulse_system_reset(reset_cycles);

    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1, $sformatf(
                 "after %0d-cycle system reset", reset_cycles));

    // Persistence on: Test-Logic-Reset leaves chrst_n released and
    // persistence set.
    check_chrst_n_in_tlr(1'b1, "persistence on");
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                 "after TMS Test-Logic-Reset");

    // Persistence off: Test-Logic-Reset asserts chrst_n, which Run-Test/Idle
    // releases.
    load_ir(6'(CLAMP_RELEASE_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd0,
                 "after CLAMP_RELEASE");
    check_chrst_n_in_tlr(1'b0, "persistence off");
    check_scan_observable("CHK-TMP-CHRST", "jtag_bsr_chrst_n", 1'b1, "Run-Test/Idle");

    check_idcode_value(idcode, "after system reset and TLR");

    finalize_family_checker();
  endtask

endclass : dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq
