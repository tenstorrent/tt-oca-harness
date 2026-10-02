// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_km_mem_smoke_test (`--items sep_km_mem_smoke_test`): runs
// sep_km_mem_smoke_test_seq on the environment's virtual sequencer once per
// pass. The testlist loads the committed KM ROM image with +km_rom_hex. The
// scenario issues no cpu_ctrl CSR read, so it requires no scoreboard
// feature.

class sep_km_mem_smoke_test extends sep_base_test;
  `uvm_component_utils(sep_km_mem_smoke_test)

  function new(string name = "sep_km_mem_smoke_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_km_mem_smoke_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_KM_MEM_SMOKE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_KM_TEST_LOOPS";
  endfunction

endclass : sep_km_mem_smoke_test
