// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smc_multi_reset_csr_persistence_test
// (`--items smc_multi_reset_csr_persistence_test`): runs
// smc_multi_reset_csr_persistence_test_seq on the environment's virtual
// sequencer once per pass and requires the scoreboard's scratch_csr feature,
// so a pass whose scratch reads never reached the predictor fails at
// finalization. The predictor re-baselines on the cool reset this scenario
// drives (smc_csr_reset_epoch), so it is judging the post-reset content too.

class smc_multi_reset_csr_persistence_test extends smc_base_test;
  `uvm_component_utils(smc_multi_reset_csr_persistence_test)

  function new(string name = "smc_multi_reset_csr_persistence_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureScratchCsr);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_multi_reset_csr_persistence_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_MULTI_RESET_CSR_PERSISTENCE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_RESET_TEST_LOOPS";
  endfunction

endclass : smc_multi_reset_csr_persistence_test
