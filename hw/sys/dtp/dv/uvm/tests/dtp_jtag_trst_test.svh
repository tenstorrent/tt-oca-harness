// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_test — asynchronous TRST reset and recovery: runs
// dtp_jtag_trst_test_seq at the looped
// floor, each pass proving TRST forces Test-Logic-Reset from distinct start
// states and that IDCODE reads back after every recovery. The aggregate
// per-cycle TAP-state legality (CHK-TAP-STATE, the cocotb checker's
// per-step evidence) lives in the env's dtp_tap_fsm_checker and is armed as
// required here.

class dtp_jtag_trst_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_trst_test)

  function new(string name = "dtp_jtag_trst_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR"});
    cfg.require_feature(DtpFeatureIdcode);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_trst_test_seq::type_id::create("jtag_trst_seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_TRST_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_trst_test
