// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// smc_regblock_sparse_strobe_test (`--items smc_regblock_sparse_strobe_test`)
// runs the wide register-block strobe scenario and requires its scoreboard.

class smc_regblock_sparse_strobe_test extends smc_base_test;
  `uvm_component_utils(smc_regblock_sparse_strobe_test)

  function new(string name = "smc_regblock_sparse_strobe_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_regblock_sparse_strobe_test_seq::type_id::create("seq");
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureRegblockWide);
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_REGBLOCK_SPARSE_STROBE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_CSR_TEST_LOOPS";
  endfunction

endclass : smc_regblock_sparse_strobe_test
