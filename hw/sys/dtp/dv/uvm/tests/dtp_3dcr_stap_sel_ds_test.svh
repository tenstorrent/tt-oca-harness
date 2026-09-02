// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_3dcr_stap_sel_ds_test — I/O (die-stack) STAP selection, gating, isolation, and recovery via
// composed TAP_3DCR chain scans
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_3dcr_stap_sel_ds_test extends dtp_base_test;
  `uvm_component_utils(dtp_3dcr_stap_sel_ds_test)

  function new(string name = "dtp_3dcr_stap_sel_ds_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
    seq.scenario = "stap_sel_ds";
    return seq;
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_3DCR_STAP_SEL_DS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_3dcr_stap_sel_ds_test
