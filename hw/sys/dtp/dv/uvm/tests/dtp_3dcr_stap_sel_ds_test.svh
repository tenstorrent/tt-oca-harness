// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_3dcr_stap_sel_ds_test — I/O (die-stack) STAP selection, gating, isolation, and
// recovery via composed TAP_3DCR chain scans, with a downstream ocah_jtag_vip
// TAP behind every STAP host port so the primary evidence is end-to-end:
// downstream IDCODE and DS_TDR readback through the selected STAP, the
// downstream register frozen in Test-Logic-Reset while the port is gated,
// and recovery against real downstream state. The host-port temporal windows
// remain as corroboration.
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_3dcr_stap_sel_ds_test extends dtp_base_test;
  `uvm_component_utils(dtp_3dcr_stap_sel_ds_test)

  function new(string name = "dtp_3dcr_stap_sel_ds_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // Every port carries a downstream TAP so the isolation neighbor has one too.
  virtual function bit [DtpStapCount-1:0] stap_ds_attach_mask();
    return '1;
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
    seq.scenario = "stap_sel_ds";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_3DCR_STAP_SEL_DS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_3dcr_stap_sel_ds_test
