// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_periph_bus_err_misaligned_test (`--items
// sep_periph_bus_err_misaligned_test`): runs
// sep_periph_bus_err_misaligned_test_seq on the environment's virtual
// sequencer once per pass. The scenario reads only status CSRs outside the
// cpu_ctrl_csr predicted set, so the test requires no scoreboard feature.

class sep_periph_bus_err_misaligned_test extends sep_base_test;
  `uvm_component_utils(sep_periph_bus_err_misaligned_test)

  function new(string name = "sep_periph_bus_err_misaligned_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_periph_bus_err_misaligned_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_PERIPH_BUS_ERR_MISALIGNED_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_SYSTEM_TEST_LOOPS";
  endfunction

endclass : sep_periph_bus_err_misaligned_test
