// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP sanity scenario sequence, carrying the DTP_VPLAN.adoc section 0.1
// procedure on the shared ocah_jtag_vip agent, in the steps the cocotb twin
// (seq_lib/dtp_sanity_test_seq.py) logs:
//   1. power-on and system reset, every debug disable held fail-closed (the
//      random walks shift random TDI into whatever instruction they load),
//      TAP reset;
//   2. a deterministic walk over all 32 legal TAP transitions; the env's
//      dtp_tap_fsm_checker model-checks every TCK cycle, and the test
//      asserts full closure via check_fsm_closure() once this pass's
//      sequence completes (CHK-TAP-VISIT-ALL);
//   3. the reset-and-idle, DR, IR and pause legs in a seeded order, every
//      raw TMS step judged against the state it must land in
//      (CHK-TAP-STATE);
//   4. BYPASS (6-bit IR 0x00) loaded and decoded as itself, then its 1-TCK
//      TDI-to-TDO latency over fixed and random patterns;
//   5. Test-Logic-Reset selects IDCODE, and IDCODE reads across IR churn
//      are stable with the marker bit set (env.m_jtag_checker).
//      +DTP_JTAG_TAP_CHECKER_NEGATIVE arms a wrong expected IDCODE so the
//      run must fail;
//   6. navigation to all sixteen states in a seeded order, then
//      test_cfg.rand_walks hops to seeded states, each landing judged
//      (CHK-TAP-GOTO) and followed by a 1..8-step raw TMS walk with random
//      TDI;
//   7. Test-Logic-Reset through five TMS-high cycles.
// The goto landings, the directed steps and the BYPASS decode
// (CHK-IR-DECODE) land on the per-pass family checker, whose expectations
// +DTP_JTAG_FAMILY_CHECKER_NEGATIVE corrupts.

class dtp_sanity_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_sanity_test_seq)

  // Longest raw TMS walk after a navigation landing.
  localparam int unsigned MaxWalkSteps = 8;

  // Seeded goto hops per pass, each followed by a raw TMS walk
  // (+DTP_RAND_WALKS through test_cfg.rand_walks).
  protected function int unsigned rand_walks();
    return test_cfg.rand_walks;
  endfunction

  function new(string name = "dtp_sanity_test_seq");
    super.new(name);
  endfunction

  // -----------------------------------------------------------------
  // Deterministic directed walk covering all 32 legal edges by
  // construction, issued as ONE raw item; the checker model-checks every
  // step and the test independently asserts closure afterwards. Starts
  // and ends in Test-Logic-Reset; the last five steps are consecutive
  // TMS=1 cycles.
  // -----------------------------------------------------------------
  task run_deterministic_walk();
    bit walk[] = '{
            // TLR self-loop, RTI, full DR leg incl. pause/exit2 re-shift
            1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0,
            1'b1, 1'b0, 1'b1, 1'b1, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0, 1'b1,
            // full IR leg incl. pause/exit2 re-shift, Select-IR -> TLR
            1'b1, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b1,
            1'b1, 1'b1, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0, 1'b1, 1'b1, 1'b1,
            // Exit2-DR -> Update-DR edge
            1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b1, 1'b1,
            // Exit2-IR -> Update-IR edge
            1'b1, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b1, 1'b1,
            // back to TLR via five consecutive TMS=1 cycles
            1'b0, 1'b1, 1'b1, 1'b1, 1'b1, 1'b1
        };
    bit tdi[];
    tdi = new[walk.size()];
    `uvm_info(get_type_name(), $sformatf(
                                   "deterministic FSM walk: %0d TMS steps for 32-edge closure",
                                   walk.size()), UVM_LOW)
    raw_walk(walk, tdi);
    check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after deterministic walk");
  endtask

  // Directed legs (cocotb check_reset_and_idle, check_dr_path,
  // check_ir_path, check_pause_paths): every raw TMS step judged against
  // the state it must land in.
  task check_reset_and_idle();
    reset_to_tlr();
    repeat (3) tms_expect(1'b0, RUN_TEST_IDLE);
    tms_expect(1'b1, SELECT_DR_SCAN);
    tms_expect(1'b1, SELECT_IR_SCAN);
    tms_expect(1'b1, TEST_LOGIC_RESET);
    tms_expect(1'b0, RUN_TEST_IDLE);
  endtask

  task check_dr_path();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    tms_expect(1'b1, SELECT_DR_SCAN);
    tms_expect(1'b0, CAPTURE_DR);
    tms_expect(1'b0, SHIFT_DR);
    repeat (3) tms_expect(1'b0, SHIFT_DR);
    tms_expect(1'b1, EXIT1_DR);
    tms_expect(1'b1, UPDATE_DR);
    tms_expect(1'b0, RUN_TEST_IDLE);
  endtask

  task check_ir_path();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    tms_expect(1'b1, SELECT_DR_SCAN);
    tms_expect(1'b1, SELECT_IR_SCAN);
    tms_expect(1'b0, CAPTURE_IR);
    tms_expect(1'b0, SHIFT_IR);
    repeat (3) tms_expect(1'b0, SHIFT_IR);
    tms_expect(1'b1, EXIT1_IR);
    tms_expect(1'b1, UPDATE_IR);
    tms_expect(1'b0, RUN_TEST_IDLE);
  endtask

  task check_pause_paths();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    tms_expect(1'b1, SELECT_DR_SCAN);
    tms_expect(1'b0, CAPTURE_DR);
    tms_expect(1'b0, SHIFT_DR);
    tms_expect(1'b1, EXIT1_DR);
    tms_expect(1'b0, PAUSE_DR);
    repeat (2) tms_expect(1'b0, PAUSE_DR);
    tms_expect(1'b1, EXIT2_DR);
    tms_expect(1'b0, SHIFT_DR);
    tms_expect(1'b1, EXIT1_DR);
    tms_expect(1'b1, UPDATE_DR);
    tms_expect(1'b0, RUN_TEST_IDLE);
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    tms_expect(1'b1, SELECT_DR_SCAN);
    tms_expect(1'b1, SELECT_IR_SCAN);
    tms_expect(1'b0, CAPTURE_IR);
    tms_expect(1'b0, SHIFT_IR);
    tms_expect(1'b1, EXIT1_IR);
    tms_expect(1'b0, PAUSE_IR);
    repeat (2) tms_expect(1'b0, PAUSE_IR);
    tms_expect(1'b1, EXIT2_IR);
    tms_expect(1'b0, SHIFT_IR);
    tms_expect(1'b1, EXIT1_IR);
    tms_expect(1'b1, UPDATE_IR);
    tms_expect(1'b0, RUN_TEST_IDLE);
  endtask

  // The four directed legs in a seeded order.
  task run_directed_legs();
    int unsigned legs[$] = {0, 1, 2, 3};
    legs.shuffle();
    foreach (legs[i]) begin
      case (legs[i])
        0: check_reset_and_idle();
        1: check_dr_path();
        2: check_ir_path();
        default: check_pause_paths();
      endcase
    end
  endtask

  // CHK-TAP-GOTO: navigate to `target` through the VIP's shortest-TMS-path
  // planner and compare the DUT's one-hot TAP state with it, then walk
  // 1..MaxWalkSteps seeded raw TMS steps with random TDI.
  task goto_and_walk(ocah_jtag_tap_state_e target, string context_s);
    int unsigned steps = $urandom_range(MaxWalkSteps, 1);
    bit tms[] = new[steps];
    bit tdi[] = new[steps];
    goto_state(target);
    family_check("CHK-TAP-GOTO", "TAP state after goto", 64'(tb_vif.tap_state),
                 64'(16'h1 << int'(target)), $sformatf("target=%s %s", target.name(), context_s));
    foreach (tms[i]) begin
      tms[i] = $urandom_range(1);
      tdi[i] = $urandom_range(1);
    end
    raw_walk(tms, tdi);
  endtask

  // Every TAP state once in a seeded order, then rand_walks() hops to
  // seeded states (cocotb check_random_state_navigation).
  task run_random_state_navigation();
    ocah_jtag_tap_state_e states[$];
    for (int unsigned s = 0; s < 16; s++) states.push_back(ocah_jtag_tap_state_e'(s));
    states.shuffle();
    foreach (states[i])
      goto_and_walk(states[i], $sformatf("shuffled %0d/%0d", i + 1, states.size()));
    for (int unsigned h = 1; h <= rand_walks(); h++)
      goto_and_walk(ocah_jtag_tap_state_e'($urandom_range(15)), $sformatf(
                    "walk %0d/%0d", h, rand_walks()));
  endtask

  // TLR must select the device-identification register: a DR scan right
  // after Test-Logic-Reset (no IR load) reads IDCODE, and repeated IDCODE
  // reads across IR churn stay stable with the marker bit set.
  task run_idcode_checks();
    localparam int unsigned IdcodeReads = 3;
    bit [63:0] observed;
    bit [63:0] reads [IdcodeReads];
    bit [31:0] expected_idcode = DtpDefaultIdcode;
    bit stable;

    if (test_cfg.tap_checker_negative) begin
      expected_idcode ^= 32'h2;
      `uvm_info(get_type_name(),
                $sformatf(
                    "NEGATIVE VALIDATION: arming wrong expected IDCODE 0x%08h instead of 0x%08h",
                    expected_idcode, DtpDefaultIdcode), UVM_LOW)
    end

    goto_tlr_via_tms();
    step(1'b0);  // TLR -> RTI (scan legs start from Run-Test/Idle)
    shift_dr(64'h0, 32, observed);
    if (evidence != null)
      void'(evidence.expect_equal(
          "CHK-TAP-TLR-IDCODE", observed[31:0], expected_idcode, "DR scan after TLR, no IR load"
      ));

    for (int unsigned r = 0; r < IdcodeReads; r++) begin
      // IR churn between reads: BYPASS then back to IDCODE.
      if (r > 0) load_ir(BYPASS_ALT_INSTR);
      read_idcode(observed);
      reads[r] = observed;
      if (evidence != null)
        void'(evidence.expect_equal(
            "CHK-IDCODE-RAW",
            observed[31:0],
            expected_idcode,
            $sformatf(
                "read=%0d/%0d", r + 1, IdcodeReads)
        ));
    end

    stable = 1'b1;
    foreach (reads[r]) if (reads[r] !== reads[0]) stable = 1'b0;
    if (evidence != null) begin
      void'(evidence.expect_true(
          "CHK-IDCODE-STABLE",
          stable,
          $sformatf(
              "reads=%0d values=0x%08h,0x%08h,0x%08h",
              IdcodeReads,
              reads[0][31:0],
              reads[1][31:0],
              reads[2][31:0])
      ));
      void'(evidence.expect_equal(
          "CHK-IDCODE-MARKER", reads[0][0], 1'b1, $sformatf("raw=0x%08h bit=0", reads[0][31:0])
      ));
    end
  endtask

  task body();
    bit [63:0] rand_pattern;
    bit [63:0] bypass_patterns[$];
    int unsigned delayed_observations = 0;

    seed_scenario_rng();
    // The raw TMS walks visit Shift-x outside the scans this sequence
    // issues, so the family checker skips the scan-count cross-check.
    attach_family_checker('{"CHK-TAP-GOTO", "CHK-TAP-STATE", "CHK-IR-DECODE"}, 1'b0);
    `uvm_info(get_type_name(),
              $sformatf("DTP SV-UVM sanity (VPLAN 0.1): scenario_seed=%0d rand_walks=%0d",
                        scenario_seed, rand_walks()), UVM_LOW)

    log_step("1", "Power-on and system reset, fail-closed debug disables, TAP reset");
    sys_reset();
    // With the lifecycle disables cleared a JTAG2AXI bridge would launch
    // the garbage requests the random walks shift in. The vector settles
    // through the TCK-domain synchronizers during the TAP reset and the
    // deterministic walk, well before the random walks.
    tb_vif.drive_dbg_disable('1);
    tap_reset();

    log_step("2", "Fixed TMS walk over all 32 legal TAP transitions");
    run_deterministic_walk();

    log_step("3", "Directed TAP paths: reset and idle, DR, IR, pause legs");
    run_directed_legs();

    log_step("4", "BYPASS (IR 0x00) one-TCK TDI-to-TDO delay");
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    load_ir(BYPASS_ALT_INSTR);
    expect_decoded_instruction(BYPASS_ALT_INSTR);
    bypass_patterns.push_back(64'hA5A5_5A5A_C3C3_3C3C);
    for (int unsigned p = 0; p < 2; p++) begin
      if (!std::randomize(rand_pattern))
        `uvm_fatal(get_type_name(), "randomize() failed for BYPASS pattern")
      bypass_patterns.push_back(rand_pattern);
    end
    foreach (bypass_patterns[p]) begin
      bit [63:0] observed, expected;
      log_iteration(p + 1, bypass_patterns.size(), $sformatf(
                    "BYPASS pattern=0x%016h", bypass_patterns[p]));
      check_bypass_latency(bypass_patterns[p], 64, observed);
      // A scan that returned the 1-TCK-delayed image, where that image
      // differs from a direct passthrough, shows the DUT delayed TDI.
      expected = ocah_jtag_checker::predict_bypass_tdo(bypass_patterns[p], 64);
      if ((observed === expected) && (expected !== bypass_patterns[p])) delayed_observations++;
    end

    log_step("5", "Test-Logic-Reset selects IDCODE; IDCODE reads are stable");
    run_idcode_checks();

    log_step("6", "Randomized TAP state navigation and walks with random TDI");
    run_random_state_navigation();

    // Full FSM closure of this pass is asserted by the test via
    // env.m_fsm_checker after this sequence returns.
    log_step("7", "Test-Logic-Reset on five TMS-high cycles");
    goto_tlr_via_tms();

    if (evidence != null)
      void'(evidence.expect_true(
          "CHK-NONVAC",
          (bypass_patterns.size() >= 3) && (delayed_observations > 0),
          $sformatf(
              "bypass_patterns=%0d delayed_observations=%0d",
              bypass_patterns.size(),
              delayed_observations)
      ));
    finalize_family_checker();
  endtask

endclass : dtp_sanity_test_seq
