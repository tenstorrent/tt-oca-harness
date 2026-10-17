// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// SEP_IN cold CSR wakes through filter/remapper register clock gates.
class smc_fabric_reg_clock_gate_test extends smc_base_test;
  `uvm_component_utils(smc_fabric_reg_clock_gate_test)
  function new(string name = "smc_fabric_reg_clock_gate_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureFabricReg);
  endfunction
  virtual function ocah_sequence create_scenario_seq();
    smc_fabric_reg_clock_gate_test_seq seq = smc_fabric_reg_clock_gate_test_seq::type_id::create(
        "seq"
    );
    seq.ref_model = m_env.m_fabric_reg_ref_model;
    return seq;
  endfunction
  virtual function string specific_loops_knob();
    return "SMC_FABRIC_REG_CLOCK_GATE_TEST_LOOPS";
  endfunction
endclass : smc_fabric_reg_clock_gate_test
