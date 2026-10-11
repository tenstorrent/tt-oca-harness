// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs watchdog count-gating and always-count priority checks across core reset.

class smc_wdt_core_awake_gate_test extends smc_base_test;
  `uvm_component_utils(smc_wdt_core_awake_gate_test)

  function new(string name = "smc_wdt_core_awake_gate_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureWdtCsr);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_wdt_core_awake_gate_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_WDT_CORE_AWAKE_GATE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_WDT_TEST_LOOPS";
  endfunction
endclass : smc_wdt_core_awake_gate_test
