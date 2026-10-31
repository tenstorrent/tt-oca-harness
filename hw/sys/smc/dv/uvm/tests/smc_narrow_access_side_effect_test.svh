// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs documented narrow-read and null-write side effects through SEP_IN.
class smc_narrow_access_side_effect_test extends smc_base_test;
  `uvm_component_utils(smc_narrow_access_side_effect_test)
  function new(string name = "smc_narrow_access_side_effect_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureMutexSema);
  endfunction
  virtual function ocah_sequence create_scenario_seq();
    return smc_narrow_access_side_effect_test_seq::type_id::create("seq");
  endfunction
  virtual function string specific_loops_knob();
    return "SMC_NARROW_ACCESS_SIDE_EFFECT_TEST_LOOPS";
  endfunction
  virtual function string group_loops_knob();
    return "SMC_CSR_TEST_LOOPS";
  endfunction
endclass : smc_narrow_access_side_effect_test
