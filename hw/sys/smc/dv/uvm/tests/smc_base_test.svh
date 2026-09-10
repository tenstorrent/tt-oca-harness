// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC base test (ocah_test realization): builds the two configuration
// levels and the environment, walks the power-good / cold-reset ladder, and
// runs every scenario as a virtual sequence on the environment's virtual
// sequencer through the library's looped-scenario runner.
//
//   1. build smc_test_cfg: seed and random volume from the library
//      accessors, the knob-derived controls, then the test's
//      configure_test_cfg() hook (required scoreboard features);
//      srandom(seed) + randomize() draws the three clock periods;
//   2. derive smc_env_cfg from it and publish both through uvm_config_db;
//      build smc_env;
//   3. bring_up(): the cocotb smc_base_test._bring_up ladder through
//      smc_tb_if in ref-clock cycles of the randomized period;
//      run_looped_scenario() (ocah_test) then starts create_scenario_seq()
//      on m_env.m_vseqr once per pass with scenario_seed = seed + pass.
//
// Knobs (plusargs here, environment variables in the cocotb twin
// tests/smc_base_test.py): +<specific>=N per test, +<group>=N per group,
// +SMC_TEST_LOOPS=N suite-wide, +SMC_RANDOM_COUNT=N random volume per pass;
// the negative-validation switch is read into smc_test_cfg (read_knobs).
// The pass banner comes from ocah_test.

class smc_base_test extends ocah_test;
  `uvm_component_utils(smc_base_test)

  // Ref-clock cycles of the bring-up ladder (cocotb _bring_up parity).
  localparam int unsigned PowergoodDelayCycles = 10;
  localparam int unsigned ColdReleaseDelayCycles = 10;

  smc_test_cfg test_cfg;
  smc_env_cfg  env_cfg;
  smc_env      m_env;

  function new(string name = "smc_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    test_cfg = smc_test_cfg::type_id::create("test_cfg");
    test_cfg.seed         = base_seed();
    test_cfg.random_count = random_count();
    test_cfg.read_knobs();
    configure_test_cfg(test_cfg);
    // The one draw before run_phase: the bench-level dimensions (the
    // three clock periods) come from the runner seed through srandom(),
    // so a run replays from the seed alone.
    test_cfg.srandom(test_cfg.seed);
    if (!test_cfg.randomize()) `uvm_fatal(get_type_name(), "smc_test_cfg randomize() failed")
    `uvm_info(get_type_name(), {"test cfg: ", test_cfg.convert2string()}, UVM_LOW)
    env_cfg = smc_env_cfg::from_test_cfg(test_cfg);
    uvm_config_db#(smc_test_cfg)::set(this, "*", "test_cfg", test_cfg);
    uvm_config_db#(smc_env_cfg)::set(this, "*", "env_cfg", env_cfg);
    m_env = smc_env::type_id::create("m_env", this);
  endfunction

  // ------------------------------------------------------------------
  // Configuration hooks.
  // ------------------------------------------------------------------

  // Scenario tests add the scoreboard features they require.
  virtual function void configure_test_cfg(smc_test_cfg cfg);
  endfunction

  virtual function string suite_loops_knob();
    return "SMC_TEST_LOOPS";
  endfunction

  virtual function string random_count_knob();
    return "SMC_RANDOM_COUNT";
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
    smc_base_test_seq smc_seq;
    if (!$cast(smc_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a smc_base_test_seq")
    smc_seq.tb_vif     = m_env.tb_vif;
    smc_seq.test_cfg   = test_cfg;
    smc_seq.env_cfg    = env_cfg;
    smc_seq.scoreboard = m_env.m_scoreboard;
  endfunction

  // Clock/reset bring-up (cocotb _bring_up parity): power-good and cold
  // reset asserted with cool reset released while the clocks start, then
  // power-good, then cold-reset release, then the post-reset settle. The
  // ladder holds the only wall-clock waits in test code, derived from the
  // randomized ref-clock period.
  virtual task bring_up();
    m_env.tb_vif.powergood  <= 1'b0;
    m_env.tb_vif.rst_cold_n <= 1'b0;
    m_env.tb_vif.rst_cool_n <= 1'b1;
    wait_ref_cycles(PowergoodDelayCycles);
    `uvm_info(get_type_name(), "asserting powergood", UVM_LOW)
    m_env.tb_vif.powergood <= 1'b1;
    wait_ref_cycles(ColdReleaseDelayCycles);
    `uvm_info(get_type_name(), "releasing cold reset", UVM_LOW)
    m_env.tb_vif.rst_cold_n <= 1'b1;
    wait_ref_cycles(test_cfg.post_reset_settle_cycles);
  endtask

  protected task wait_ref_cycles(int unsigned cycles);
    #(cycles * env_cfg.ref_clk_period_ns * 1ns);
  endtask

endclass : smc_base_test
