// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_ac_extest_train_test — AC EXTEST_TRAIN scan-loopback checks with
// per-pass family evidence (looped runner, 16-pass floor).

class dtp_jtag_ac_extest_train_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_ac_extest_train_test)

  function new(string name = "dtp_jtag_ac_extest_train_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_ac_extest_train_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_AC_EXTEST_TRAIN_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_ac_extest_train_test
