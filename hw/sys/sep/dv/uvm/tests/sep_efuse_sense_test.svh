// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_efuse_sense_test (`--items sep_efuse_sense_test`): runs
// sep_efuse_sense_test_seq on the environment's virtual sequencer once per
// pass. The scenario issues no CSR access, so the test requires no
// scoreboard feature.

class sep_efuse_sense_test extends sep_base_test;
  `uvm_component_utils(sep_efuse_sense_test)

  function new(string name = "sep_efuse_sense_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_efuse_sense_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_EFUSE_SENSE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_EFUSE_LCC_TEST_LOOPS";
  endfunction

endclass : sep_efuse_sense_test
