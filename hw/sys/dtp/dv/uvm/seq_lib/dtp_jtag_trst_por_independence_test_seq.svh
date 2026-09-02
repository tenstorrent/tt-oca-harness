// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_por_independence_test scenario sequence — POR-only TAP
// reset while TRST_N stays deasserted (the SV port of the cocotb
// dtp_jtag_trst_por_independence_test_seq):
//   * navigate to a seeded start state (Run-Test/Idle, Shift-IR, Shift-DR,
//     Pause-IR, or Pause-DR) with a seeded BYPASS/IDCODE instruction loaded;
//   * pulse power-on reset for a seeded 2..8 TCK-scale window with TRST
//     untouched and prove the TAP is in Test-Logic-Reset both during the
//     pulse and after release, before any TRST activity;
//   * TAP-reset and prove the device-identification register reads back
//     (CHK-IDCODE-RECOVERY).
//
// The POR pulse is a pure delay with no TCK edges: the env's always-on
// dtp_tap_fsm_checker has no POR awareness, so clocking TCK through the
// asynchronous reset would flag the DUT's legitimate snap to
// Test-Logic-Reset as an illegal transition. The reset independence proof
// is unchanged — the TAP state observable is asynchronous to TCK.
//
// The scan-count cross-check is disabled (cocotb use_monitor=False parity):
// the navigation path into the Pause states crosses Shift -> Exit1, which
// publishes partial scans the sequence cannot count.

class dtp_jtag_trst_por_independence_test_seq extends dtp_jtag_cmd_lib_seq;
  `uvm_object_utils(dtp_jtag_trst_por_independence_test_seq)

  // One TCK period at the harness's 10 MHz TCK.
  localparam time TckPeriod = 100ns;

  function new(string name = "dtp_jtag_trst_por_independence_test_seq");
    super.new(name);
  endfunction

  task body();
    ocah_jtag_tap_state_e state_choices[5];
    ocah_jtag_tap_state_e target;
    int unsigned por_cycles;
    bit [63:0] idcode;
    bit [IrWidth-1:0] instr;
    string required[$];

    seed_scenario_rng();
    scan_builder = null;
    required = {"CHK-TAP-RESET-TLR", "CHK-IDCODE-RECOVERY"};
    attach_family_checker(required);

    state_choices[0] = OCAH_JTAG_RUN_TEST_IDLE;
    state_choices[1] = OCAH_JTAG_SHIFT_IR;
    state_choices[2] = OCAH_JTAG_SHIFT_DR;
    state_choices[3] = OCAH_JTAG_PAUSE_IR;
    state_choices[4] = OCAH_JTAG_PAUSE_DR;
    target           = state_choices[$urandom_range(4)];
    instr            = $urandom_range(1) ? IDCODE_INSTR : BYPASS_INSTR;
    por_cycles       = $urandom_range(8, 2);
    `uvm_info(get_type_name(), $sformatf("POR independence: start=%s ir=0x%02h por_cycles=%0d",
                                         target.name(), instr, por_cycles), UVM_LOW)

    // TRST is released by the TAP-reset op and stays deasserted for the
    // rest of the scenario.
    reset_to_tlr();
    load_ir(instr);
    goto_state(target);
    check_state(tap_state_e'(16'h1 << int'(target)), "jtag_por_chk", $sformatf(
                "start state %s before POR", target.name()));

    // POR-only reset: assert pwr_on_rst with TRST high and no TCK edges.
    tb_vif.por_rst_n <= 1'b0;
    #(por_cycles * TckPeriod);
    check_state(TEST_LOGIC_RESET, "jtag_por_chk", $sformatf(
                "during POR from %s, TRST deasserted", target.name()));
    tb_vif.por_rst_n <= 1'b1;
    #(TckPeriod);
    check_state(TEST_LOGIC_RESET, "jtag_por_chk", "after POR release, before TRST");
    // Re-align sequence-side TAP tracking with the asynchronous reset.
    sync_model(OCAH_JTAG_TEST_LOGIC_RESET);

    // Recovery: TAP-reset (re-baselining the env checkers through the
    // TRST event) and prove IDCODE reads back.
    reset_to_tlr();
    read_idcode(idcode);
    family_check("CHK-IDCODE-RECOVERY", "IDCODE recovery after POR", idcode[31:0], DtpDefaultIdcode,
                 $sformatf("start_state=%s por_cycles=%0d", target.name(), por_cycles));
    finalize_family_checker();
  endtask

endclass : dtp_jtag_trst_por_independence_test_seq
