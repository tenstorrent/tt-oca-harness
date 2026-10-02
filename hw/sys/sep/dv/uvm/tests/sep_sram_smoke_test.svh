// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_sram_smoke_test (`--items sep_sram_smoke_test`): runs
// sep_sram_smoke_test_seq on the environment's virtual sequencer once per
// pass. The scenario reads and writes SRAM only, which no scoreboard feature
// predicts, so the test requires none; the proof is the sequence's own
// readback checks against the written stimulus.

class sep_sram_smoke_test extends sep_base_test;
  `uvm_component_utils(sep_sram_smoke_test)

  function new(string name = "sep_sram_smoke_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_sram_smoke_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_SRAM_SMOKE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_MEMORY_TEST_LOOPS";
  endfunction

endclass : sep_sram_smoke_test
