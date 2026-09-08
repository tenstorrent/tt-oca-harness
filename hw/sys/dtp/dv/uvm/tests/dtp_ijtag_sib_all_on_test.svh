// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ijtag_sib_all_on_test — all iJTAG SIBs open; each direct disable gates its SIB in a seeded
// order while the others stay effective
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_ijtag_sib_all_on_test extends dtp_base_test;
  `uvm_component_utils(dtp_ijtag_sib_all_on_test)

  function new(string name = "dtp_ijtag_sib_all_on_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ijtag_scan_test_seq seq = dtp_ijtag_scan_test_seq::type_id::create("seq");
    seq.scenario = "sib_all_on";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_IJTAG_SIB_ALL_ON_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_ijtag_sib_all_on_test
