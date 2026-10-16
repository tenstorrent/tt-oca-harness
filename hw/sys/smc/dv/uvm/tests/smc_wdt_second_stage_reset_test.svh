// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs per-core watchdog second-stage service and warm-reset recovery checks.

class smc_wdt_second_stage_reset_test extends smc_base_test;
  `uvm_component_utils(smc_wdt_second_stage_reset_test)

  function new(string name = "smc_wdt_second_stage_reset_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_wdt_second_stage_reset_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_WDT_SECOND_STAGE_RESET_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_WDT_TEST_LOOPS";
  endfunction
endclass : smc_wdt_second_stage_reset_test
