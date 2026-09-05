// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_runbist_test — Basic JTAG VPLAN scenario: RUNBIST instruction
// decode and looped scan-path response checks, run through the
// looped-scenario floor with per-pass seeds.

class dtp_jtag_runbist_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_runbist_test)

  function new(string name = "dtp_jtag_runbist_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_runbist_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_RUNBIST_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_runbist_test
