// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_jtag_reset_override_test (`--items smu_jtag_reset_override_test`): runs
// smu_jtag_reset_override_test_seq on the environment's virtual sequencer once
// per pass and requires the scoreboard features the scenario exercises
// (ir_decode, ic_reset_tdr) and the aggregate TAP evidence, so a pass whose
// accesses never reached the reference models fails at finalization.

class smu_jtag_reset_override_test extends smu_base_test;
  `uvm_component_utils(smu_jtag_reset_override_test)

  function new(string name = "smu_jtag_reset_override_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smu_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(dtp_env_pkg::DtpFeatureIrDecode);
    cfg.require_feature(SmuFeatureIcResetTdr);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR"});
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smu_jtag_reset_override_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMU_JTAG_RESET_OVERRIDE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMU_DTP_TEST_LOOPS";
  endfunction

endclass : smu_jtag_reset_override_test
