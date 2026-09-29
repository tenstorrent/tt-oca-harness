// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_ext_boot_seq_gate_test scenario sequence (SMU_006, the external
// boot-sequence gate), carrying the cocotb cocotb_wrapper/seq_lib/
// smu_ext_boot_seq_gate_test_seq.py semantics: S1 a cold reset released with
// ext_boot_seq_done_i held 0 and TRST high, then the settle; S2 the gated
// window: smc_fuse_reset_n_delayed_o reads 0 on every one of the sampled
// clocks while the gate reads 0; S3 the negative control: the SMC primary
// reset releases while the boot gate is still shut, since that reset is not
// gated by the pin (CHK-PRIMARY-NOT-GATED); S4 the ungate: ext_boot_seq_done_i
// driven 1, then the fuse reset releases within the bound (CHK-BOOT-SEQ-
// GATE); TIMEOUT both bounded waits completed inside their bound (CHK-
// TIMEOUT-PATHS) and the ordered fence from DUT edges, simulation-time
// stamped by a tracker armed at the release: the first primary rise
// precedes the ungate, and the first fuse rise follows both the end of the
// gated window and the ungate (CHK-NONVAC). Every pass re-runs the cold
// reset with the gate shut, so the property is proved once per pass.
// Independently, the always-on scoreboard's boot_gate feature requires the
// gate open and the sense complete at every fuse-reset release the pin
// monitor observes -- a release inside the gated window fails there as
// well; +SMU_BOOT_GATE_SCOREBOARD_NEGATIVE corrupts that prediction so the
// run must FAIL.

class smu_ext_boot_seq_gate_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_ext_boot_seq_gate_test_seq)

  localparam string ChkPrimaryNotGated = "CHK-PRIMARY-NOT-GATED";
  localparam string ChkBootSeqGate = "CHK-BOOT-SEQ-GATE";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";
  localparam string ChkNonvac = "CHK-NONVAC";

  // The cocotb scenario's constants.
  localparam int unsigned GatedSamples = 64;
  localparam int unsigned ReleaseBound = 2000;
  // Fuse-reset releases a pass causes: the ungate.
  localparam int unsigned FuseReleasesPerPass = 1;
  // Bounded-wait sites: primary_released_while_boot_gated,
  // fuse_reset_n_delayed_after_ungate.
  localparam int unsigned ExpectedTimeoutPaths = 2;
  // Step marks S1..S4, TIMEOUT, PASS: five ordered, non-decreasing deltas.
  localparam int unsigned ExpectedStepDeltas = 5;

  // First-rise stamps of the tracked outputs, in simulation time; -1 while
  // unseen.
  protected realtime m_t_primary_rise;
  protected realtime m_t_fuse_rise;
  protected realtime m_t_gated_end;
  protected realtime m_t_ungate;
  // The first-rise tracker forked for the pass.
  protected process  m_tracker;

  function new(string name = "smu_ext_boot_seq_gate_test_seq");
    super.new(name);
  endfunction

  task body();
    seed_scenario_rng();
    attach_evidence('{ChkPrimaryNotGated, ChkBootSeqGate, ChkTimeoutPaths, ChkNonvac, ChkSbMinAct});
    check_min_activity(SmuFeatureBootGate, FuseReleasesPerPass);
    `uvm_info(get_type_name(), $sformatf(
              {"SMU SV-UVM external boot-sequence gate (smu_ext_boot_seq_gate_test, SMU_006): ",
               "gated_samples=%0d release_bound=%0d; scenario_seed=%0d"},
              GatedSamples, ReleaseBound, scenario_seed), UVM_LOW)

    m_t_primary_rise = -1;
    m_t_fuse_rise    = -1;
    run_preload();
    fork
      begin
        m_tracker = process::self();
        track_first_rises();
      end
    join_none
    run_gated_window();
    run_primary_not_gated();
    run_ungate();
    if (m_tracker != null) m_tracker.kill();
    run_timeout_inventory(ChkTimeoutPaths, ExpectedTimeoutPaths);

    mark_step("PASS", "scenario complete (PASS term recorded for the NONVAC fence)");
    check_evidence(ChkNonvac, "ordered step-delta count", 64'(ordered_step_deltas()),
                   64'(ExpectedStepDeltas), $sformatf("steps=%0d", m_step_order.size()));
    check_evidence(ChkNonvac, "S3<S4 primary_release<ungate",
                   64'((m_t_primary_rise >= 0) && (m_t_primary_rise < m_t_ungate)), 64'd1,
                   $sformatf("primary_release=%0t ungate=%0t", m_t_primary_rise, m_t_ungate));
    check_evidence(ChkNonvac, "S2<S4 gated_window_end<fuse_release",
                   64'((m_t_fuse_rise >= 0) && (m_t_gated_end < m_t_fuse_rise)), 64'd1,
                   $sformatf("gated_window_end=%0t fuse_release=%0t", m_t_gated_end,
                             m_t_fuse_rise));
    check_evidence(ChkNonvac, "S4 ungate<fuse_release",
                   64'((m_t_fuse_rise >= 0) && (m_t_ungate < m_t_fuse_rise)), 64'd1, $sformatf(
                   "ungate=%0t fuse_release=%0t", m_t_ungate, m_t_fuse_rise));
    finalize_evidence();
  endtask

  // S1: gate shut, cold reset released with TRST high, the settle.
  protected task run_preload();
    mark_step("S1", {
              "PRELOAD: ext_boot_seq_done_i=0; cold reset released with TRST high; ",
              "powergood=1 (fuse reset gated)"
              });
    tb_vif.ext_boot_seq_done <= 1'b0;
    pulse_cold_reset();
    wait_ref_cycles(test_cfg.post_reset_settle_cycles);
  endtask

  // Stamp the first SMU clock at which each tracked output samples 1.
  protected task track_first_rises();
    forever begin
      @(posedge tb_vif.clk_smu);
      if ((m_t_primary_rise < 0) && pin_is("rst_primary_smc_clk_n", 1'b1))
        m_t_primary_rise = $realtime;
      if ((m_t_fuse_rise < 0) && pin_is("fuse_reset_n_delayed", 1'b1)) m_t_fuse_rise = $realtime;
    end
  endtask

  // S2: the gated window.
  protected task run_gated_window();
    int unsigned fuse_breaks = 0;
    int unsigned gate_breaks = 0;
    mark_step("S2", "GATED: ext_boot_seq_done_i=0 holds smc_fuse_reset_n_delayed_o low");
    for (int unsigned s = 0; s < GatedSamples; s++) begin
      @(posedge tb_vif.clk_smu);
      if (!pin_is("fuse_reset_n_delayed", 1'b0)) fuse_breaks++;
      if (!pin_is("ext_boot_seq_done", 1'b0)) gate_breaks++;
    end
    m_t_gated_end = $realtime;
    check_evidence(ChkBootSeqGate, "gate held 0 across the window", 64'(gate_breaks), 64'd0,
                   $sformatf("samples=%0d", GatedSamples));
    check_evidence(ChkBootSeqGate, "fuse reset 0 on every gated sample", 64'(fuse_breaks), 64'd0,
                   $sformatf("samples=%0d", GatedSamples));
  endtask

  // S3: the primary reset is not what the pin gates.
  protected task run_primary_not_gated();
    int cycles;
    mark_step("S3", "NEGATIVE CONTROL: rst_primary_smc_clk_no still releases while boot-gated");
    wait_pin_level("rst_primary_smc_clk_n", 1'b1, ReleaseBound, "primary_released_while_boot_gated",
                   cycles);
    // The poll and the tracker sample the same clock edge, and the compare
    // below can run before the tracker resumes, so the poll stamps the edge
    // when it is the first to see the 1.
    if ((cycles >= 0) && (m_t_primary_rise < 0) && pin_is("rst_primary_smc_clk_n", 1'b1))
      m_t_primary_rise = $realtime;
    check_evidence(ChkPrimaryNotGated, "primary released while gated",
                   64'(pin_is("rst_primary_smc_clk_n", 1'b1)), 64'd1, $sformatf(
                   "cycles=%0d gate=%0b", cycles, pin_is("ext_boot_seq_done", 1'b1)));
    check_evidence(ChkPrimaryNotGated, "gate still shut", 64'(pin_is("ext_boot_seq_done", 1'b0)),
                   64'd1);
  endtask

  // S4: the ungate, then the release.
  protected task run_ungate();
    int cycles;
    mark_step("S4", "UNGATE: drive ext_boot_seq_done_i=1; fuse reset release permitted");
    m_t_ungate = $realtime;
    tb_vif.ext_boot_seq_done <= 1'b1;
    wait_pin_level("fuse_reset_n_delayed", 1'b1, ReleaseBound, "fuse_reset_n_delayed_after_ungate",
                   cycles);
    if ((cycles >= 0) && (m_t_fuse_rise < 0) && pin_is("fuse_reset_n_delayed", 1'b1))
      m_t_fuse_rise = $realtime;
    check_evidence(ChkBootSeqGate, "fuse reset released after ungate",
                   64'(pin_is("fuse_reset_n_delayed", 1'b1)), 64'd1, $sformatf(
                   "cycles=%0d gated_samples=%0d", cycles, GatedSamples));
  endtask

endclass : smu_ext_boot_seq_gate_test_seq
