// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smc_reset_unit_lock_test (`--items smc_reset_unit_lock_test`): runs
// smc_reset_unit_lock_test_seq on the environment's virtual sequencer once per
// pass and requires the scoreboard's lock_csr feature, so a pass whose lock
// -pair accesses never reached the predictor fails at finalization.

class smc_reset_unit_lock_test extends smc_base_test;
  `uvm_component_utils(smc_reset_unit_lock_test)

  function new(string name = "smc_reset_unit_lock_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureLockCsr);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_reset_unit_lock_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_RESET_UNIT_LOCK_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_RESET_TEST_LOOPS";
  endfunction

endclass : smc_reset_unit_lock_test
