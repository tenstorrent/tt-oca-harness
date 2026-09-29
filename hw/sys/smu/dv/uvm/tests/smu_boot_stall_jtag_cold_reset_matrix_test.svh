// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_boot_stall_jtag_cold_reset_matrix_test (`--items
// smu_boot_stall_jtag_cold_reset_matrix_test`): runs
// smu_boot_stall_jtag_cold_reset_matrix_test_seq on the environment's virtual
// sequencer once per pass and requires the scoreboard features the scenario
// exercises (ir_decode, debug_control_tdr, boot_gate) and the aggregate TAP
// evidence, so a pass whose accesses never reached the reference models fails
// at finalization.

class smu_boot_stall_jtag_cold_reset_matrix_test extends smu_base_test;
  `uvm_component_utils(smu_boot_stall_jtag_cold_reset_matrix_test)

  function new(string name = "smu_boot_stall_jtag_cold_reset_matrix_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smu_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(dtp_env_pkg::DtpFeatureIrDecode);
    cfg.require_feature(SmuFeatureDebugControlTdr);
    cfg.require_feature(SmuFeatureBootGate);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR"});
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smu_boot_stall_jtag_cold_reset_matrix_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMU_BOOT_STALL_JTAG_COLD_RESET_MATRIX_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMU_BOOT_STALL_TEST_LOOPS";
  endfunction

endclass : smu_boot_stall_jtag_cold_reset_matrix_test
