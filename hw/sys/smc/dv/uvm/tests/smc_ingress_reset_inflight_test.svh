// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs SEP_IN held-response reset and same-ID recovery checks.
class smc_ingress_reset_inflight_test extends smc_base_test;
  `uvm_component_utils(smc_ingress_reset_inflight_test)
  function new(string name = "smc_ingress_reset_inflight_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureSpmMem);
    cfg.axi_timeout_cycles = 8192;
    cfg.enable_sep_in_reset_monitor = 1;
  endfunction
  virtual function void plumb_scenario_seq(ocah_sequence seq);
    smc_ingress_reset_inflight_test_seq reset_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(reset_seq, seq)) begin
      `uvm_fatal(get_type_name(), "Invalid ingress-reset scenario sequence")
    end
    reset_seq.reset_monitor = m_env.m_sep_in_reset_monitor;
  endfunction
  virtual function ocah_sequence create_scenario_seq();
    return smc_ingress_reset_inflight_test_seq::type_id::create("seq");
  endfunction
  virtual function string specific_loops_knob();
    return "SMC_INGRESS_RESET_INFLIGHT_TEST_LOOPS";
  endfunction
  virtual function string group_loops_knob();
    return "SMC_RESET_TEST_LOOPS";
  endfunction
endclass : smc_ingress_reset_inflight_test
