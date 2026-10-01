// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP sanity scenario sequence, carrying the full DTP_VPLAN.adoc section 0.1
// semantics on the shared ocah_jtag_vip agent:
//   * deterministic 32-edge TAP FSM closure walk (16 states x tms in {0,1});
//     the env's dtp_tap_fsm_checker model-checks every TCK cycle, and the
//     test asserts full closure via check_fsm_closure() once this pass's
//     sequence completes (CHK-TAP-VISIT-ALL). Randomized TMS walks and
//     targeted goto_random_state() hops (VIP shortest-path navigation,
//     landing state checked against the DUT one-hot observable) run IN
//     ADDITION as stress stimulus, not as the closure mechanism, so
//     pass/fail is seed-independent;
//   * BYPASS (6-bit IR 0x00) loaded once and decoded as itself, then its
//     1-TCK TDI-to-TDO latency over fixed + random patterns (checked here
//     from the DR_SCAN item responses);
//   * clean scan-path returns to Run-Test/Idle, final Test-Logic-Reset via
//     five consecutive TMS=1 cycles;
//   * named TAP-contract evidence through env.m_jtag_checker:
//     reset-to-TLR, TLR-selects-IDCODE, IDCODE value/stability/marker, and
//     reconstructed scan lengths. +DTP_JTAG_TAP_CHECKER_NEGATIVE is the
//     documented negative-validation hook: it arms a WRONG
//     expected IDCODE so the run must FAIL, proving the named-evidence path
//     rejects a bad expectation end to end;
//   * the goto landings (CHK-TAP-GOTO) and the BYPASS decode (CHK-IR-DECODE)
//     on the per-pass family checker, whose expectations
//     +DTP_JTAG_FAMILY_CHECKER_NEGATIVE corrupts.

class dtp_sanity_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_sanity_test_seq)

  // Seeded random walks per pass come from test_cfg.rand_walks
  // (+DTP_RAND_WALKS, default 16: the suite-wide minimum-iteration floor).
  localparam int unsigned RandWalkSteps = 64;
  localparam int unsigned GotoHops = 16;

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

  // Randomized raw-TMS stress walks (reproducible via +ntb_random_seed;
  // every choice logged, every step model-checked by the env checker).
  task run_random_walks();
    int unsigned walks = rand_walks();
    for (int unsigned w = 0; w < walks; w++) begin
      bit [RandWalkSteps-1:0] tms_bits, tdi_bits;
      bit tms[], tdi[];
      if (!std::randomize(tms_bits, tdi_bits))
        `uvm_fatal(get_type_name(), "randomize() failed for TMS stress walk")
      `uvm_info(get_type_name(), $sformatf(
                "random TMS stress walk %0d/%0d: tms=0x%016h tdi=0x%016h",
                w + 1,
                walks,
                tms_bits,
                tdi_bits
                ), UVM_LOW)
      tms = new[RandWalkSteps];
      tdi = new[RandWalkSteps];
      for (int unsigned i = 0; i < RandWalkSteps; i++) begin
        tms[i] = tms_bits[i];
        tdi[i] = tdi_bits[i];
      end
      raw_walk(tms, tdi);
      goto_tlr_via_tms();
    end
  endtask

  // CHK-TAP-GOTO: targeted navigation through the VIP's shortest-TMS-path
  // planner. Each hop picks a random target state, navigates there via
  // goto_random_state(), and compares the DUT's one-hot TAP state
  // observable against the target (every intermediate TCK step is also
  // model-checked by the env's dtp_tap_fsm_checker).
  task run_goto_state_hops();
    ocah_jtag_tap_state_e reached;
    for (int unsigned h = 0; h < GotoHops; h++) begin
      goto_random_state(reached);
      `uvm_info(get_type_name(), $sformatf(
                "goto hop %0d/%0d: target=%s", h + 1, GotoHops, reached.name()), UVM_LOW)
      family_check("CHK-TAP-GOTO", "TAP state after goto", 64'(tb_vif.tap_state),
                   64'(16'h1 << int'(reached)), $sformatf(
                   "hop=%0d/%0d target=%s", h + 1, GotoHops, reached.name()));
      check_state(dtp_tap_state_e'(16'h1 << int'(reached)), "sanity_goto_state_chk", $sformatf(
                  "after goto hop %0d/%0d", h + 1, GotoHops));
    end
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
    attach_family_checker('{"CHK-TAP-GOTO", "CHK-IR-DECODE"}, 1'b0);
    // Start-of-pass banner: intent, per-pass seed, and randomized volume.
    `uvm_info(get_type_name(),
              $sformatf({"DTP SV-UVM sanity (VPLAN 0.1): FSM 32-edge closure + BYPASS 1-TCK ",
                         "latency + IDCODE + scan path; scenario_seed=%0d rand_walks=%0dx%0d steps"
                          }, scenario_seed, rand_walks(), RandWalkSteps), UVM_LOW)

    // Power-on/system reset sequencing, then TAP reset (VPLAN 0.1 step 1).
    sys_reset();
    // The random TMS/TDI stress loads arbitrary instructions and shifts
    // arbitrary data registers; with the lifecycle disables cleared a
    // JTAG2AXI bridge would launch garbage bus requests. This scenario
    // proves the TAP alone, so it holds every debug disable at the
    // fail-closed vector (the bridge scenarios enable what they exercise).
    // The vector settles through the TCK-domain synchronizers during the
    // TAP reset and the deterministic walk, well before the stress walks.
    tb_vif.drive_dbg_disable('1);
    tap_reset();

    // sanity_fsm_visit_chk: deterministic 32-edge closure walk.
    run_deterministic_walk();

    // sanity_bypass_latency_chk: BYPASS via 6-bit IR 0x00, fixed + random patterns.
    step(1'b0);  // TLR -> RTI
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
      check_bypass_latency(bypass_patterns[p], 64, observed);
      // A scan that returned the 1-TCK-delayed image, where that image
      // differs from a direct passthrough, shows the DUT delayed TDI.
      expected = ocah_jtag_checker::predict_bypass_tdo(bypass_patterns[p], 64);
      if ((observed === expected) && (expected !== bypass_patterns[p])) delayed_observations++;
    end

    // CHK-TAP-TLR-IDCODE / CHK-IDCODE-*: identification-register contracts.
    run_idcode_checks();

    // Randomized raw-TMS stress on top of the deterministic closure.
    run_random_walks();

    // CHK-TAP-GOTO: targeted shortest-path navigation hops.
    run_goto_state_hops();

    // sanity_scan_path_chk epilogue: TLR via five TMS=1 cycles. Full
    // FSM closure of this pass is asserted by the test via
    // env.m_fsm_checker after this sequence returns.
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
