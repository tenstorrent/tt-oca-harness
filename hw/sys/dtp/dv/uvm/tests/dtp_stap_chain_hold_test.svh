// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_stap_chain_hold_test — with the PTAP 3DCR select clear, IR and DR scans leave the STAP
// chain untouched: the host scan controls stay quiet, no STAP forwards, and every SIB reads back
// closed once the select is set (looped runner with per-pass family evidence).

class dtp_stap_chain_hold_test extends dtp_base_test;
  `uvm_component_utils(dtp_stap_chain_hold_test)

  function new(string name = "dtp_stap_chain_hold_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
    seq.scenario = "stap_chain_hold";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_STAP_CHAIN_HOLD_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_stap_chain_hold_test
