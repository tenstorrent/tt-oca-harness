// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs reset-unit external register lane and isolation checks through SEP_IN.
class smc_external_reg_lane_test extends smc_base_test;
  `uvm_component_utils(smc_external_reg_lane_test)
  function new(string name = "smc_external_reg_lane_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function ocah_sequence create_scenario_seq();
    return smc_external_reg_lane_test_seq::type_id::create("seq");
  endfunction
  virtual function string specific_loops_knob();
    return "SMC_EXTERNAL_REG_LANE_TEST_LOOPS";
  endfunction
  virtual function string group_loops_knob();
    return "SMC_CSR_TEST_LOOPS";
  endfunction
endclass : smc_external_reg_lane_test
