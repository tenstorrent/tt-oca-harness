// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_otbn_mem_smoke_test (`--items sep_otbn_mem_smoke_test`): runs
// sep_otbn_mem_smoke_test_seq on the environment's virtual sequencer once
// per pass. The scenario reads no predicted sep_cpu_ctrl register, so the
// test requires no scoreboard feature; its evidence is the readbacks and
// the OTBN SRAM counter probes the sequence grades.

class sep_otbn_mem_smoke_test extends sep_base_test;
  `uvm_component_utils(sep_otbn_mem_smoke_test)

  function new(string name = "sep_otbn_mem_smoke_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_otbn_mem_smoke_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_OTBN_MEM_SMOKE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_CRYPTO_TEST_LOOPS";
  endfunction

endclass : sep_otbn_mem_smoke_test
