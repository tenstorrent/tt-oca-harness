// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// smc_lock_pipelined_write_test checks keyed WDT and SS_CONFIG lock ordering
// (`--items smc_lock_pipelined_write_test`) with required AW/W/B overlap.

class smc_lock_pipelined_write_test extends smc_base_test;
  `uvm_component_utils(smc_lock_pipelined_write_test)

  function new(string name = "smc_lock_pipelined_write_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureLockCsr);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_lock_pipelined_write_test_seq::type_id::create("seq");
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    smc_lock_pipelined_write_test_seq pipeline_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(pipeline_seq, seq)) `uvm_fatal(get_type_name(), "invalid pipeline write sequence")
    pipeline_seq.final_pass = seq.loop_index + 1 ==
        loop_count(specific_loops_knob(), group_loops_knob(), default_loops());
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_LOCK_PIPELINED_WRITE_TEST_LOOPS";
  endfunction
endclass : smc_lock_pipelined_write_test
