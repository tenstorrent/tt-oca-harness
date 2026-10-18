// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Runs occupied-mailbox cool-reset and fresh-traffic recovery checks.
class smc_mailbox_cool_reset_recovery_test extends smc_base_test;
  `uvm_component_utils(smc_mailbox_cool_reset_recovery_test)
  function new(string name = "smc_mailbox_cool_reset_recovery_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smc_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmcFeatureMailboxFifo);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smc_mailbox_cool_reset_recovery_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMC_MAILBOX_COOL_RESET_RECOVERY_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMC_MAILBOX_TEST_LOOPS";
  endfunction
endclass : smc_mailbox_cool_reset_recovery_test
