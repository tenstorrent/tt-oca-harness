// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_ext_boot_seq_gate_test (`--items smu_ext_boot_seq_gate_test`): runs
// smu_ext_boot_seq_gate_test_seq on the environment's virtual sequencer once
// per pass and requires the scoreboard features the scenario exercises
// (boot_gate), so a pass whose accesses never reached the reference models
// fails at finalization.

class smu_ext_boot_seq_gate_test extends smu_base_test;
  `uvm_component_utils(smu_ext_boot_seq_gate_test)

  function new(string name = "smu_ext_boot_seq_gate_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smu_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SmuFeatureBootGate);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smu_ext_boot_seq_gate_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMU_EXT_BOOT_SEQ_GATE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMU_BOOT_GATE_TEST_LOOPS";
  endfunction

endclass : smu_ext_boot_seq_gate_test
