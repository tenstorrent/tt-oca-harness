// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_zero_length_bypass_test — Basic JTAG VPLAN scenario:
// ZERO_LENGTH_BYPASS direct pass-through checks with a plain-BYPASS
// reference point, and the same instruction in a STAP chain with a
// downstream TAP behind a seeded STAP, run through the looped-scenario floor
// with per-pass seeds.

class dtp_jtag_zero_length_bypass_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_zero_length_bypass_test)

  function new(string name = "dtp_jtag_zero_length_bypass_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(DtpFeatureBypass);
  endfunction

  // The chain leg draws its STAP per pass, so every port carries a
  // downstream TAP.
  virtual function bit [DtpStapCount-1:0] stap_ds_attach_mask();
    return '1;
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_zero_length_bypass_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_ZERO_LENGTH_BYPASS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_zero_length_bypass_test
