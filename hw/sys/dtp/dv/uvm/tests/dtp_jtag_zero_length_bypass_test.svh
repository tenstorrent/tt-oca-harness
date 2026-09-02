// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_zero_length_bypass_test — Basic JTAG VPLAN scenario:
// ZERO_LENGTH_BYPASS direct pass-through checks with a plain-BYPASS
// reference point, run through the looped-scenario floor with per-pass
// seeds.

class dtp_jtag_zero_length_bypass_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_zero_length_bypass_test)

  function new(string name = "dtp_jtag_zero_length_bypass_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    return dtp_jtag_zero_length_bypass_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG_ZERO_LENGTH_BYPASS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_zero_length_bypass_test
