// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ext_stap_scan_test — the extended STAP host scan interface follows the PTAP 3DCR select,
// stays quiet under the stap_host disable, and recovers without reset
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_ext_stap_scan_test extends dtp_base_test;
  `uvm_component_utils(dtp_ext_stap_scan_test)

  function new(string name = "dtp_ext_stap_scan_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
    seq.scenario = "ext_stap_scan";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_EXT_STAP_SCAN_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_ext_stap_scan_test
