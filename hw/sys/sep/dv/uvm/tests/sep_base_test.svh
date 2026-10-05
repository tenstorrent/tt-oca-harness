// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP base test (ocah_test realization): builds the two configuration
// levels and the environment, walks the primary-reset ladder with the CPU
// held off, and runs every scenario as a virtual sequence on the
// environment's virtual sequencer through the library's looped-scenario
// runner.
//
//   1. build sep_test_cfg: seed and random volume from the library
//      accessors, the knob-derived controls, then the test's
//      configure_test_cfg() hook (required scoreboard features);
//      the clock periods are the fixed 800 MHz / 100 MHz pair;
//   2. derive sep_env_cfg from it and publish both through uvm_config_db;
//      build sep_env;
//   3. bring_up(): the cocotb sep_base_test.release_no_cpu_reset ladder
//      through sep_tb_if in system-clock cycles of the 1.25 ns period;
//      run_looped_scenario() (ocah_test) then starts create_scenario_seq()
//      on m_env.m_vseqr once per pass with scenario_seed = seed + pass.
//
// Knobs (plusargs here, environment variables in the cocotb twin
// cocotb/tests/sep_base_test.py): +<specific>=N per test, +<group>=N per group,
// +SEP_TEST_LOOPS=N suite-wide, +SEP_RANDOM_COUNT=N random volume per pass;
// the negative-validation switch is read into sep_test_cfg (read_knobs).
// The pass banner comes from ocah_test.

class sep_base_test extends ocah_test;
  `uvm_component_utils(sep_base_test)

  // Time from zero to the reset assertion, as a fraction of the system clock
  // period. The tb_top clocks run from time zero and the system clock is the
  // fastest of them (first edge at half its period), so a quarter period puts
  // the falling edge on rst_n ahead of every clock edge of the run (cocotb
  // assert_cold_reset parity: every async-reset flop loads its reset value
  // from the edge, not from a clock, and no clocked assertion samples the
  // pre-reset X state).
  localparam real ResetAssertSysClkFraction = 0.25;

  sep_test_cfg test_cfg;
  sep_env_cfg  env_cfg;
  sep_env      m_env;

  function new(string name = "sep_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    test_cfg = sep_test_cfg::type_id::create("test_cfg");
    test_cfg.seed         = base_seed();
    test_cfg.random_count = random_count();
    test_cfg.read_knobs();
    configure_test_cfg(test_cfg);
    // The one draw before run_phase. sep_test_cfg declares no rand field
    // (the clock periods are fixed), so this draws nothing; seeding from the
    // runner seed keeps any rand field replayable from the seed alone.
    test_cfg.srandom(test_cfg.seed);
    if (!test_cfg.randomize()) `uvm_fatal(get_type_name(), "sep_test_cfg randomize() failed")
    `uvm_info(get_type_name(), {"test cfg: ", test_cfg.convert2string()}, UVM_LOW)
    env_cfg = sep_env_cfg::from_test_cfg(test_cfg);
    uvm_config_db#(sep_test_cfg)::set(this, "*", "test_cfg", test_cfg);
    uvm_config_db#(sep_env_cfg)::set(this, "*", "env_cfg", env_cfg);
    m_env = sep_env::type_id::create("m_env", this);
  endfunction

  // ------------------------------------------------------------------
  // Configuration hooks.
  // ------------------------------------------------------------------

  // Scenario tests add the scoreboard features they require.
  virtual function void configure_test_cfg(sep_test_cfg cfg);
  endfunction

  virtual function string suite_loops_knob();
    return "SEP_TEST_LOOPS";
  endfunction

  virtual function string random_count_knob();
    return "SEP_RANDOM_COUNT";
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
    sep_base_test_seq sep_seq;
    if (!$cast(sep_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a sep_base_test_seq")
    sep_seq.tb_vif   = m_env.tb_vif;
    sep_seq.test_cfg = test_cfg;
    sep_seq.env_cfg  = env_cfg;
  endfunction

  // Clock/reset bring-up (cocotb release_no_cpu_reset parity): the boot/run
  // controls sit at their idle values from time zero, the primary reset is
  // asserted with a real falling edge before the first clock edge, held for
  // reset_hold_cycles system clocks, and released; the pass starts
  // post_reset_cycles later. The ladder holds the only wall-clock waits in
  // test code, derived from the system-clock period.
  virtual task bring_up();
    #(ResetAssertSysClkFraction * env_cfg.sys_clk_period_ns * 1ns);
    `uvm_info(get_type_name(), "asserting rst_n (CPU held off)", UVM_LOW)
    m_env.tb_vif.rst_n <= 1'b0;
    wait_sys_cycles(test_cfg.reset_hold_cycles);
    `uvm_info(get_type_name(), "releasing rst_n", UVM_LOW)
    m_env.tb_vif.rst_n <= 1'b1;
    wait_sys_cycles(test_cfg.post_reset_cycles);
  endtask

  protected task wait_sys_cycles(int unsigned cycles);
    #(cycles * env_cfg.sys_clk_period_ns * 1ns);
  endtask

endclass : sep_base_test
