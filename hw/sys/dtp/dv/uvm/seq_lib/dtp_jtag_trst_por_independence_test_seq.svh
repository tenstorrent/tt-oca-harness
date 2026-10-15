// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_por_independence_test scenario sequence — POR-only TAP
// reset while TRST_N stays deasserted (the SV port of the cocotb
// dtp_jtag_trst_por_independence_test_seq):
//   * navigate to a seeded start state (Run-Test/Idle, Shift-IR, Shift-DR,
//     Pause-IR, or Pause-DR) with a seeded instruction other than IDCODE
//     loaded (BYPASS 0x00, BYPASS 0x3F, or SAMPLE/PRELOAD);
//   * hold power-on reset for a seeded 2..8 TCK periods with TRST untouched
//     and TCK idle (pulse_por), and prove the TAP is in Test-Logic-Reset
//     with TRST_N high during the pulse (CHK-TAP-POR-TLR) and that the
//     tb_top assertion counter advanced (CHK-RESET-COUNT);
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
    bit [15:0] state_under_por;
    bit trst_n_under_por;
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
    instr      = random_non_idcode_preload();
    por_cycles = $urandom_range(8, 2);
    ctx        = $sformatf("start_state=%s por_cycles=%0d", target.name(), por_cycles);
    `uvm_info(get_type_name(), $sformatf("POR independence: %s ir=0x%02h", ctx, instr), UVM_LOW)

    // TRST is released by the TAP-reset op and stays deasserted for the
    // rest of the scenario.
    log_step("1", $sformatf("Park the TAP in %s with TRST_N released", target.name()));
    reset_to_tlr();
    load_ir(instr);
    goto_state(target);
    check_state(dtp_tap_state_e'(16'h1 << int'(target)), "jtag_por_chk", $sformatf(
                "start state %s before POR", target.name()));

    log_step("2", $sformatf("Hold power-on reset for %0d TCK periods with TCK idle", por_cycles));
    pulse_por(por_cycles, state_under_por, trst_n_under_por);
    check_tap_state(PorCheckId, state_under_por, TEST_LOGIC_RESET, {"during POR ", ctx});
    family_check(PorCheckId, "TRST_N deasserted during POR", 64'(trst_n_under_por), 64'd1, ctx);
    check_state(TEST_LOGIC_RESET, "jtag_por_chk", "after POR release, before any TCK edge");

    log_step("3", "TLR -> RTI by TMS, then a DR scan with no IR load reads IDCODE");
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag_por_chk", "after TLR->RTI step");
    shift_dr(64'h0, 32, idcode);
    family_check("CHK-IDCODE-RECOVERY", "IDCODE DR scan after POR, no IR load, no TRST",
                 idcode[31:0], DtpDefaultIdcode, ctx);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_trst_por_independence_test_seq
