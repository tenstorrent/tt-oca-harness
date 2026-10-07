// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Test base: the knob accessor, the seed, the looped-scenario runner, and
// the pass-banner contract. "UVM TEST PASSED" is emitted only from
// report_phase and only when the global UVM_ERROR/UVM_FATAL counts are both
// zero (uvm-log parser contract); never from sequence or scoreboard code.
// This is the one accessor of the simulator seed plusarg (+ntb_random_seed
// on VCS, appended by the runner).
//
// Looped-scenario contract (cocotb OcahTest parity): every looped scenario
// runs at least MinDefaultLoops passes, each with its own scenario seed
// (runner seed + loop index), so directed scenarios re-prove back-to-back
// recovery and randomized scenarios add stimulus diversity. Loop counts
// resolve from knobs without touching test code:
//   +<specific>=N (per test), +<group>=N (per group), +<suite>=N (suite-wide),
//   +<random_count knob>=N (random patterns per pass, default 5).
// A bench base test implements the hooks: build its test cfg and env in
// build_phase, walk the reset ladder in bring_up(), name its virtual
// sequencer in scenario_sequencer(), and plumb the scenario sequence in
// plumb_scenario_seq(); a thin scenario test overrides create_scenario_seq()
// and the knob-name hooks and inherits run_phase(). A scenario whose seeded
// iterations are the rows of one pass runs run_single_scenario() from its
// run_phase() instead.

class ocah_test extends uvm_test;
  `uvm_component_utils(ocah_test)

  // Every looped scenario runs at least this many passes by default.
  localparam int unsigned MinDefaultLoops = 16;

  function new(string name = "ocah_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // ------------------------------------------------------------------
  // Seed and knobs.
  // ------------------------------------------------------------------

  // Runner-provided seed; the only read of the simulator seed plusarg.
  static function int unsigned base_seed();
    int unsigned seed;
    if (!$value$plusargs("ntb_random_seed=%d", seed)) seed = 1;
    return seed;
  endfunction

  // Knob names the bench binds; an empty name skips that level.
  virtual function string suite_loops_knob();
    return "";
  endfunction

  virtual function string random_count_knob();
    return "";
  endfunction

  virtual function string specific_loops_knob();
    return "";
  endfunction

  virtual function string group_loops_knob();
    return "";
  endfunction

  virtual function int unsigned default_loops();
    return MinDefaultLoops;
  endfunction

  // Random patterns or operations per pass (default 5).
  function int unsigned random_count();
    if (random_count_knob().len() == 0) return 5;
    return ocah_knobs::get_int_min(random_count_knob(), 5, 1);
  endfunction

  // Loop-count resolution: the specific per-test knob wins, then the group
  // knob, then the suite knob, then the default (floored at
  // MinDefaultLoops). An explicit 0 is a configuration defect.
  function int unsigned loop_count(string specific_knob, string group_knob,
                                   int unsigned default_count = MinDefaultLoops);
    string sources[$] = {specific_knob, group_knob, suite_loops_knob()};
    foreach (sources[i]) begin
      if (sources[i].len() == 0) continue;
      if ($test$plusargs({sources[i], "="}))
        return ocah_knobs::get_int_min(sources[i], MinDefaultLoops, 1);
    end
    return (default_count > MinDefaultLoops) ? default_count : MinDefaultLoops;
  endfunction

  // ------------------------------------------------------------------
  // Looped-scenario hooks.
  // ------------------------------------------------------------------

  // Build one pass's scenario sequence (factory-created, unconfigured).
  virtual function ocah_sequence create_scenario_seq();
    return null;
  endfunction

  // The bench virtual sequencer every scenario pass starts on.
  virtual function uvm_sequencer_base scenario_sequencer();
    return null;
  endfunction

  // Hand a scenario pass the handles it needs (TB interface, evidence).
  virtual function void plumb_scenario_seq(ocah_sequence seq);
  endfunction

  // Clock and reset bring-up through the bench TB interface; runs once
  // before the first pass.
  virtual task bring_up();
  endtask

  // Per-pass preparation before the scenario is plumbed and started.
  virtual function void pre_scenario_pass(int unsigned idx);
  endfunction

  task run_looped_scenario();
    run_scenario_passes(loop_count(specific_loops_knob(), group_loops_knob(), default_loops()));
  endtask

  // One pass of create_scenario_seq() at the runner seed, after bring_up().
  task run_single_scenario();
    run_scenario_passes(1);
  endtask

  // Plumb one sequence and start it on the scenario sequencer, or on `seqr`
  // when given. The cocotb twin is OcahTest.start_seq.
  task start_seq(ocah_sequence seq, uvm_sequencer_base seqr = null);
    if (seq == null) `uvm_fatal(get_type_name(), "start_seq() was handed a null sequence")
    if (seqr == null) seqr = scenario_sequencer();
    if (seqr == null) `uvm_fatal(get_type_name(), "scenario_sequencer() returned null")
    plumb_scenario_seq(seq);
    seq.start(seqr);
  endtask

  protected task run_scenario_passes(int unsigned loops);
    int unsigned seed   = base_seed();
    int unsigned rcount = random_count();
    bring_up();
    for (int unsigned idx = 0; idx < loops; idx++) begin
      ocah_sequence seq = create_scenario_seq();
      if (seq == null)
        `uvm_fatal(get_type_name(),
                   "scenario test must override create_scenario_seq() (or run_phase())")
      seq.scenario_seed = seed + idx;
      seq.random_count  = rcount;
      seq.loop_index    = idx;
      pre_scenario_pass(idx);
      `uvm_info(get_type_name(), $sformatf(
                "scenario pass %0d/%0d: %s scenario_seed=%0d random_count=%0d",
                idx + 1,
                loops,
                seq.get_type_name(),
                seq.scenario_seed,
                rcount
                ), UVM_LOW)
      start_seq(seq);
    end
  endtask

  // Default run flow for looped tests; bespoke tests override run_phase().
  task run_phase(uvm_phase phase);
    phase.raise_objection(this, {get_type_name(), " running"});
    run_looped_scenario();
    phase.drop_objection(this, {get_type_name(), " done"});
  endtask

  function void report_phase(uvm_phase phase);
    uvm_report_server svr = uvm_report_server::get_server();
    super.report_phase(phase);
    if (svr.get_severity_count(UVM_FATAL) == 0 && svr.get_severity_count(UVM_ERROR) == 0)
      `uvm_info(get_type_name(), "UVM TEST PASSED", UVM_NONE)
    else `uvm_info(get_type_name(), "UVM TEST FAILED", UVM_NONE)
  endfunction

endclass : ocah_test
