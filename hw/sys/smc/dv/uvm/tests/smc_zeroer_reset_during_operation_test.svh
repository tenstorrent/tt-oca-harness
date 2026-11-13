// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs both Zeroer cool-reset phases and grades recovery through SYS_OUT.
class smc_zeroer_reset_during_operation_test extends smc_base_test;
  `uvm_component_utils(smc_zeroer_reset_during_operation_test)
  function new(string name = "smc_zeroer_reset_during_operation_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureZeroerRange);
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    smc_zeroer_reset_during_operation_test_seq zeroer_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(zeroer_seq, seq)) begin
      `uvm_fatal(get_type_name(), "Invalid Zeroer reset scenario sequence")
    end
    zeroer_seq.zeroer_ref_model = m_env.m_zeroer_range_ref_model;
    zeroer_seq.zeroer_observer = m_env.m_zeroer_burst_observer;
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_zeroer_reset_during_operation_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_ZEROER_RESET_DURING_OPERATION_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_ZEROER_TEST_LOOPS";
  endfunction
endclass : smc_zeroer_reset_during_operation_test
