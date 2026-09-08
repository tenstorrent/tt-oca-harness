// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Sequence base: the looped-scenario contract every bench scenario carries.
// The base test sets scenario_seed (runner seed + pass index), random_count,
// and loop_index before start(); body() calls seed_scenario_rng() first so
// every draw in the pass, in this sequence or a helper it calls, is
// replayable from the simulator seed plus the pass index. Pattern and salt
// helpers forward to ocah_rng; step and iteration logging use the shared
// formats. With the default item type this is the parent of every
// <dut>_base_test_seq virtual sequence; typed by a VIP item it is the parent
// a VIP master sequence adopts. The cocotb twin is ocah_lib.OcahSequence.
//
// No evidence handle here: its type is the protocol checker the bench needs
// (ocah_jtag_checker, ocah_checker), so the bench base sequence declares it.

class ocah_sequence #(
  type REQ = uvm_sequence_item,
  type RSP = REQ
) extends uvm_sequence #(REQ, RSP);
  `uvm_object_param_utils(ocah_sequence#(REQ, RSP))

  // Per-pass seed: runner seed + loop index, set by the base test.
  int unsigned scenario_seed = 0;
  // Random patterns or operations per pass.
  int unsigned random_count = 5;
  // Pass index within the looped run (0-based); pass 0 follows bring-up.
  int unsigned loop_index = 0;

  function new(string name = "ocah_sequence");
    super.new(name);
  endfunction

  // Seed this body() process from the per-pass scenario seed. start()
  // forks body() in its own process, so the seed scopes to this pass and
  // to every helper the body calls.
  function void seed_scenario_rng();
    process p = process::self();
    if (p != null) p.srandom(scenario_seed);
  endfunction

  // Seed salted by a label, for a helper that needs its own stream.
  function int unsigned salted_seed(string label);
    return ocah_rng::salted_seed(scenario_seed, label);
  endfunction

  static function bit [63:0] bit_mask(int unsigned width);
    return ocah_rng::bit_mask(width);
  endfunction

  function bit [63:0] random_pattern(int unsigned width);
    return ocah_rng::random_pattern(width);
  endfunction

  // Directed corners first, `random_count` seeded random patterns on top.
  function void directed_patterns(int unsigned width, ref bit [63:0] patterns[$]);
    ocah_rng::directed_patterns(width, random_count, patterns);
  endfunction

  // Shared log formats (UVM_LOW: steps; UVM_MEDIUM: iterations).
  function void log_step(string step_s, string message);
    `uvm_info(get_type_name(), $sformatf("Step %s: %s", step_s, message), UVM_LOW)
  endfunction

  function void log_iteration(int unsigned index, int unsigned total, string message);
    `uvm_info(get_type_name(), $sformatf("Iteration %0d/%0d: %s", index, total, message),
              UVM_MEDIUM)
  endfunction

endclass : ocah_sequence
