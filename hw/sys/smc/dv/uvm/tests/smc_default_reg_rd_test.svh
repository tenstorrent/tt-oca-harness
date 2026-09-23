// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smc_default_reg_rd_test (`--items smc_default_reg_rd_test`): runs
// smc_default_reg_rd_test_seq on the environment's virtual sequencer once per
// pass and requires the scoreboard's default_reg feature, so a pass whose
// catalogued reads never reached the predictor fails at finalization.

class smc_default_reg_rd_test extends smc_base_test;
  `uvm_component_utils(smc_default_reg_rd_test)

  function new(string name = "smc_default_reg_rd_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureDefaultReg);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_default_reg_rd_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_DEFAULT_REG_RD_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_AXIL_TEST_LOOPS";
  endfunction

endclass : smc_default_reg_rd_test
