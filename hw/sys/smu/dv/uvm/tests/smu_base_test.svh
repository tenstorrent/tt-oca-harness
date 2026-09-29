// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU base test (ocah_test realization): builds the two configuration levels
// and the environment, walks the power-good / cold-reset ladder, and runs
// every scenario as a virtual sequence on the environment's virtual sequencer
// through the library's looped-scenario runner.    1. build smu_test_cfg: seed
// and random volume from the library      accessors, the knob-derived
// controls, then the test's      configure_test_cfg() hook (required
// scoreboard features, aggregate      JTAG evidence policy, the TCK floor);
// srandom(seed) + randomize()      draws the clock periods, the TCK period,
// and the settle;   2. derive smu_env_cfg from it and publish both through
// uvm_config_db;      build smu_env;   3. bring_up(): the cocotb
// smu_base_test.bring_up ladder through      smu_tb_if in ref-clock cycles of
// the randomized period -- a TAP reset      before the cold-reset release and
// another after it, so the IC_RESET      TDR loads its reset image instead of
// holding the SMC in reset --      then the bounded polls of the cold-stable
// and primary reset      releases; run_looped_scenario() (ocah_test) then
// starts      create_scenario_seq() on m_env.m_vseqr once per pass with
// scenario_seed = seed + pass.  Knobs (plusargs here, environment variables in
// the cocotb twin cocotb_wrapper/tests/smu_base_test.py): +<specific>=N per
// test, +<group>=N per group, +SMU_TEST_LOOPS=N suite-wide,
// +SMU_RANDOM_COUNT=N random volume per pass; the negative-validation switches
// are read into smu_test_cfg (read_knobs). The pass banner comes from
// ocah_test.

class smu_base_test extends ocah_test;
  `uvm_component_utils(smu_base_test)

  smu_test_cfg test_cfg;
  smu_env_cfg  env_cfg;
  smu_env      m_env;

  function new(string name = "smu_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    test_cfg = smu_test_cfg::type_id::create("test_cfg");
    test_cfg.seed         = base_seed();
    test_cfg.random_count = random_count();
    test_cfg.read_knobs();
    configure_test_cfg(test_cfg);
    // The one draw before run_phase: the bench-level dimensions (clocks,
    // TCK, and settle) come from the runner seed through srandom(), so a
    // run replays from the seed alone.
    test_cfg.srandom(test_cfg.seed);
    if (!test_cfg.randomize()) `uvm_fatal(get_type_name(), "smu_test_cfg randomize() failed")
    `uvm_info(get_type_name(), {"test cfg: ", test_cfg.convert2string()}, UVM_LOW)
    env_cfg = smu_env_cfg::from_test_cfg(test_cfg);
    uvm_config_db#(smu_test_cfg)::set(this, "*", "test_cfg", test_cfg);
    uvm_config_db#(smu_env_cfg)::set(this, "*", "env_cfg", env_cfg);
    m_env = smu_env::type_id::create("m_env", this);
  endfunction

  // ------------------------------------------------------------------
  // Configuration hooks.
  // ------------------------------------------------------------------

  // Scenario tests add the scoreboard features and the aggregate JTAG
  // evidence IDs they require.
  virtual function void configure_test_cfg(smu_test_cfg cfg);
  endfunction

  virtual function string suite_loops_knob();
    return "SMU_TEST_LOOPS";
  endfunction

  virtual function string random_count_knob();
    return "SMU_RANDOM_COUNT";
  endfunction

  // ------------------------------------------------------------------
  // Looped-scenario hooks.
  // ------------------------------------------------------------------

  virtual function uvm_sequencer_base scenario_sequencer();
    return m_env.m_vseqr;
  endfunction

  // Standard handle plumbing for every scenario pass; scenario-specific
  // handles are added by the thin tests, which call super first.
  virtual function void plumb_scenario_seq(ocah_sequence seq);
    smu_base_test_seq smu_seq;
    if (!$cast(smu_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a smu_base_test_seq")
    smu_seq.tb_vif     = m_env.tb_vif;
    smu_seq.dtp_tb_vif = m_env.dtp_tb_vif;
    smu_seq.test_cfg   = test_cfg;
    smu_seq.env_cfg    = env_cfg;
    smu_seq.scoreboard = m_env.m_scoreboard;
    smu_seq.evidence   = m_env.m_jtag_checker;
  endfunction

  // Fresh scan-reconstruction window per pass: the builder's bounded
  // history would otherwise saturate across the 16-pass floor.
  virtual function void pre_scenario_pass(int unsigned idx);
    m_env.m_scan_builder.clear_history();
  endfunction

  // Clock/reset bring-up (cocotb bring_up parity): power-good and cold
  // reset asserted while the clocks start, a TAP reset so the DTP IC_RESET
  // TDR holds its reset image rather than a power-up override that would
  // keep the SMC in cold reset, then power-good, then cold-reset release
  // after the power-good sync and the 32-cycle cold deglitch, a second TAP
  // reset, then the post-reset settle and the bounded polls of the
  // cold-stable and primary reset releases. The ladder holds the only
  // wall-clock waits in test code, derived from the randomized ref-clock
  // period.
  virtual task bring_up();
    m_env.tb_vif.powergood  <= 1'b0;
    m_env.tb_vif.rst_cold_n <= 1'b0;
    wait_ref_cycles(test_cfg.powergood_delay_cycles);
    tap_reset_on_jtag_seqr("before power-good");
    `uvm_info(get_type_name(), "asserting powergood", UVM_LOW)
    m_env.tb_vif.powergood <= 1'b1;
    wait_ref_cycles(test_cfg.cold_release_delay_cycles);
    `uvm_info(get_type_name(), "releasing cold reset", UVM_LOW)
    m_env.tb_vif.rst_cold_n <= 1'b1;
    tap_reset_on_jtag_seqr("after cold-reset release");
    wait_ref_cycles(test_cfg.post_reset_settle_cycles);
    wait_reset_released("rst_cold_stable_ref_clk_no", m_env.tb_vif.rst_cold_stable_ref_clk_n);
    wait_reset_released("rst_primary_smc_clk_no", m_env.tb_vif.rst_primary_smc_clk_n);
    `uvm_info(get_type_name(), "SMU bring-up complete (powergood + cold/primary resets released)",
              UVM_LOW)
  endtask

  // One TAP reset operation straight on the JTAG agent sequencer (the
  // bring-up runs before any scenario pass owns the virtual sequencer).
  protected task tap_reset_on_jtag_seqr(string when);
    smu_jtag_tap_reset_seq op = smu_jtag_tap_reset_seq::type_id::create("bring_up_tap_reset");
    `uvm_info(get_type_name(), {"TAP reset ", when}, UVM_LOW)
    op.entry_state = OCAH_JTAG_TEST_LOGIC_RESET;
    op.start(m_env.m_jtag_env.m_sequencer);
  endtask

  // Bounded ref-clock poll of one reset-release observable (cocotb
  // wait_signal_high parity); expiry is an error.
  protected task wait_reset_released(string name, ref logic observable);
    int unsigned cycles = 0;
    while (observable !== 1'b1) begin
      if (cycles >= test_cfg.reset_release_timeout_cycles) begin
        `uvm_error(get_type_name(), $sformatf("%s never released within %0d ref clocks", name,
                                              cycles))
        return;
      end
      wait_ref_cycles(1);
      cycles++;
    end
    `uvm_info(get_type_name(), $sformatf("%s released after %0d ref clocks", name, cycles),
              UVM_MEDIUM)
  endtask

  protected task wait_ref_cycles(int unsigned cycles);
    #(cycles * env_cfg.ref_clk_period_ns * 1ns);
  endtask

endclass : smu_base_test
