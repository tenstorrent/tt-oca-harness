// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_por_independence_test scenario sequence — POR-only TAP
// reset while TRST_N stays deasserted (the SV port of the cocotb
// dtp_jtag_trst_por_independence_test_seq):
//   * navigate to a seeded start state (Run-Test/Idle, Shift-IR, Shift-DR,
//     Pause-IR, or Pause-DR) with a seeded BYPASS/IDCODE instruction loaded;
//   * hold power-on reset for a seeded 2..8 TCK periods with TRST untouched
//     and TCK idle, and prove the TAP is in Test-Logic-Reset with TRST_N
//     high during the pulse and after release (CHK-TAP-POR-TLR);
//   * step TLR -> RTI by TMS alone and prove a DR scan with no IR load and
//     no TRST activity reads the device-identification register the reset
//     reloaded (CHK-IDCODE-RECOVERY).
//
// The POR pulse is a pure delay with no TCK edges: the TAP state observable
// is asynchronous to TCK, so the proof needs none, and the env's always-on
// dtp_tap_fsm_checker re-baselines on the tb_top POR assertion counter
// before it judges the first step after the pulse.
//
// The scan-count cross-check is disabled (cocotb use_monitor=False parity):
// the navigation path into the Pause states crosses Shift -> Exit1, which
// publishes partial scans the sequence cannot count.

class dtp_jtag_trst_por_independence_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_trst_por_independence_test_seq)

  localparam string PorCheckId = "CHK-TAP-POR-TLR";

  function new(string name = "dtp_jtag_trst_por_independence_test_seq");
    super.new(name);
  endfunction

  task body();
    ocah_jtag_tap_state_e state_choices[5];
    ocah_jtag_tap_state_e target;
    int unsigned por_cycles;
    bit [63:0] idcode;
    bit [IrWidth-1:0] instr;
    string ctx;
    string required[$];

    seed_scenario_rng();
    scan_builder = null;
    required = {"CHK-TAP-RESET-TLR", PorCheckId, "CHK-IDCODE-RECOVERY"};
    attach_family_checker(required);

    state_choices[0] = OCAH_JTAG_RUN_TEST_IDLE;
    state_choices[1] = OCAH_JTAG_SHIFT_IR;
    state_choices[2] = OCAH_JTAG_SHIFT_DR;
    state_choices[3] = OCAH_JTAG_PAUSE_IR;
    state_choices[4] = OCAH_JTAG_PAUSE_DR;
    target     = state_choices[$urandom_range(4)];
    instr      = $urandom_range(1) ? IDCODE_INSTR : BYPASS_INSTR;
    por_cycles = $urandom_range(8, 2);
    ctx        = $sformatf("start_state=%s por_cycles=%0d", target.name(), por_cycles);
    `uvm_info(get_type_name(), $sformatf("POR independence: %s ir=0x%02h", ctx, instr), UVM_LOW)

    // TRST is released by the TAP-reset op and stays deasserted for the
    // rest of the scenario.
    `uvm_info(get_type_name(), $sformatf("Step 1: Park the TAP in %s with TRST_N released",
                                         target.name()), UVM_LOW)
    reset_to_tlr();
    load_ir(instr);
    goto_state(target);
    check_state(tap_state_e'(16'h1 << int'(target)), "jtag_por_chk", $sformatf(
                "start state %s before POR", target.name()));

    `uvm_info(get_type_name(), $sformatf(
                                   "Step 2: Hold power-on reset for %0d TCK periods with TCK idle",
                                   por_cycles), UVM_LOW)
    tb_vif.por_rst_n <= 1'b0;
    wait_tck_periods(por_cycles);
    family_check(PorCheckId, "TAP state during POR", 64'(tb_vif.tap_state), 64'(TEST_LOGIC_RESET),
                 ctx);
    family_check(PorCheckId, "TRST_N deasserted during POR", 64'(jtag_vif.trst_n), 64'd1, ctx);
    check_state(TEST_LOGIC_RESET, "jtag_por_chk", $sformatf(
                "during POR from %s, TRST deasserted", target.name()));
    tb_vif.por_rst_n <= 1'b1;
    wait_tck_periods(1);
    check_state(TEST_LOGIC_RESET, "jtag_por_chk", "after POR release, before any TCK edge");
    // Re-align sequence-side TAP tracking with the asynchronous reset.
    sync_model(OCAH_JTAG_TEST_LOGIC_RESET);

    `uvm_info(get_type_name(),
              "Step 3: TLR -> RTI by TMS, then a DR scan with no IR load reads IDCODE", UVM_LOW)
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag_por_chk", "after TLR->RTI step");
    shift_dr(64'h0, 32, idcode);
    family_check("CHK-IDCODE-RECOVERY", "IDCODE DR scan after POR, no IR load, no TRST",
                 idcode[31:0], DtpDefaultIdcode, ctx);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_trst_por_independence_test_seq
