// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smc_register_sanity_test (`--items smc_register_sanity_test`): runs
// smc_register_sanity_test_seq on the
// environment's virtual sequencer once per pass and requires the
// scoreboard's scratch_csr feature, so a pass whose scratch reads never
// reached the predictor fails at finalization.

class smc_register_sanity_test extends smc_base_test;
  `uvm_component_utils(smc_register_sanity_test)

  function new(string name = "smc_register_sanity_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureScratchCsr);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_register_sanity_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_REGISTER_SANITY_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_AXIL_TEST_LOOPS";
  endfunction

endclass : smc_register_sanity_test
