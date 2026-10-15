// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_test scenario sequence — asynchronous TRST reset and
// recovery with named evidence (the SV port of the cocotb
// dtp_jtag_trst_test_seq):
//   * from every TAP state other than Test-Logic-Reset, in a seeded order,
//     each with a seeded instruction other than IDCODE loaded (BYPASS 0x00,
//     BYPASS 0x3F, or SAMPLE/PRELOAD), drive TRST low and prove the TAP is
//     in Test-Logic-Reset before any TCK edge (CHK-TAP-TRST-ASYNC), then
//     hold it low for a seeded 2..8 TCK cycles with TMS low, which would
//     leave Test-Logic-Reset were the reset not holding it
//     (CHK-TAP-TRST-TLR);
//   * release TRST for a seeded 1..3 cycles, step TLR -> RTI by TMS alone,
//     and prove a DR scan with no IR load reads the device-identification
//     register the reset selected (CHK-IDCODE-RAW). goto_state reaches
//     Update-IR from Capture-IR with no Shift-IR, and that update itself
//     selects IDCODE, so from Update-IR only the two reset checks tell a
//     working reset from a broken one;
//   * CHK-NONVAC rejects a degenerate pass (a start state missed or
//     repeated, sub-2 TRST widths, or missed recoveries).
// The per-cycle TAP-state legality lives in the env's dtp_tap_fsm_checker
// (aggregate CHK-TAP-STATE armed by the test); partial scans cut short by
// TRST are dropped by the scan builder, so the pin-level scan cross-check
// stays consistent and remains enabled for this scenario.

class dtp_jtag_trst_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_trst_test_seq)

  function new(string name = "dtp_jtag_trst_test_seq");
    super.new(name);
  endfunction

  // From `state`, assert TRST_N, judge the reset, release, and read IDCODE.
  protected task reset_from(input ocah_jtag_tap_state_e state, output int unsigned assert_cycles,
                            output bit recovered);
    int unsigned release_cycles = $urandom_range(3, 1);
    bit [IrWidth-1:0] instr = random_non_idcode_preload();
    bit [63:0] idcode;
    string ctx;
    assert_cycles = $urandom_range(8, 2);
    `uvm_info(get_type_name(), $sformatf("TRST: start=%s ir=0x%02h assert=%0d release=%0d",
                                         state.name(), instr, assert_cycles, release_cycles),
              UVM_LOW)

    log_step("1", $sformatf("Park the TAP in %s with a non-IDCODE instruction", state.name()));
    reset_to_tlr();
    load_ir(instr);
    goto_state(state);
    check_state(dtp_tap_state_e'(16'h1 << int'(state)), "jtag_trst_chk", $sformatf(
                "start state %s before TRST", state.name()));

    set_trst(1'b0, assert_cycles);
    ctx = $sformatf("trst_from=%s cycles=%0d", state.name(), assert_cycles);
    log_step("2", "TRST_N low: Test-Logic-Reset before any TCK edge and under TMS low");
    check_tap_state("CHK-TAP-TRST-ASYNC", trst_async_state(), TEST_LOGIC_RESET, {
                    "before any TCK edge ", ctx});
    check_tap_state("CHK-TAP-TRST-TLR", tb_vif.tap_state, TEST_LOGIC_RESET, {
                    "after TMS-low TCK cycles under TRST ", ctx});
    check_state(TEST_LOGIC_RESET, "jtag_trst_chk", {"while TRST held ", ctx});
    set_trst(1'b1, release_cycles);

    // TLR -> RTI by TMS alone; the DR scan with no IR load reads the
    // register the reset selected.
    log_step("3", "TRST_N released; Run-Test/Idle by TMS, then IDCODE with no IR load");
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag_trst_chk", "after TLR->RTI step");
    shift_dr(64'h0, 32, idcode);
    family_check("CHK-IDCODE-RAW", "DR scan with no IR load after TRST release", idcode[31:0],
                 DtpDefaultIdcode, ctx);
    recovered = (idcode[31:0] == DtpDefaultIdcode);
  endtask

  task body();
    ocah_jtag_tap_state_e states[$];
    ocah_jtag_tap_state_e tap_state;
    int unsigned non_reset_states = tap_state.num() - 1;
    bit visited[ocah_jtag_tap_state_e];
    int unsigned trst_cycles[$];
    int unsigned min_cycles[$];
    int unsigned idcode_ok = 0;
    string required[$];

    seed_scenario_rng();
    required = {
      "CHK-TAP-RESET-TLR", "CHK-TAP-TRST-ASYNC", "CHK-TAP-TRST-TLR", "CHK-IDCODE-RAW", "CHK-NONVAC"
    };
    attach_family_checker(required);

    for (int i = int'(OCAH_JTAG_RUN_TEST_IDLE); i <= int'(OCAH_JTAG_UPDATE_IR); i++)
      states.push_back(ocah_jtag_tap_state_e'(i));
    states.shuffle();

    foreach (states[s]) begin
      int unsigned cycles;
      bit recovered;
      `uvm_info(get_type_name(), $sformatf(
                "TRST pass %0d/%0d: start=%s", s + 1, states.size(), states[s].name()), UVM_LOW)
      reset_from(states[s], cycles, recovered);
      visited[states[s]] = 1'b1;
      trst_cycles.push_back(cycles);
      if (recovered) idcode_ok++;
    end

    min_cycles = trst_cycles.min();
    if (m_family != null)
      void'(m_family.expect_true(
          "CHK-NONVAC",
          (visited.num() == non_reset_states) && (min_cycles[0] >= 2)
              && (idcode_ok == non_reset_states),
          $sformatf(
              "start_states=%0d/%0d min_trst_cycles=%0d idcode_recovered=%0d/%0d",
              visited.num(),
              non_reset_states,
              min_cycles[0],
              idcode_ok,
              non_reset_states)
      ));
    finalize_family_checker();
  endtask

endclass : dtp_jtag_trst_test_seq
