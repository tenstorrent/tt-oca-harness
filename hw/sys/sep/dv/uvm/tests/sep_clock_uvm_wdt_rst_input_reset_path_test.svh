// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_clock_uvm_wdt_rst_input_reset_path_test
// (`--items sep_clock_uvm_wdt_rst_input_reset_path_test`): runs
// sep_clock_uvm_wdt_rst_input_reset_path_test_seq on the environment's
// virtual sequencer once per pass. The scenario does no CSR access, so it
// requires no scoreboard feature. The `uvm` in the name is the cocotb
// PyUVM suite name.

class sep_clock_uvm_wdt_rst_input_reset_path_test extends sep_base_test;
  `uvm_component_utils(sep_clock_uvm_wdt_rst_input_reset_path_test)

  function new(string name = "sep_clock_uvm_wdt_rst_input_reset_path_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_clock_uvm_wdt_rst_input_reset_path_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_CLOCK_UVM_WDT_RST_INPUT_RESET_PATH_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_SYSTEM_TEST_LOOPS";
  endfunction

endclass : sep_clock_uvm_wdt_rst_input_reset_path_test
