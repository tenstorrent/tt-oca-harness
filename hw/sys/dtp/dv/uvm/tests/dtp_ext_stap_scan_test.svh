// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ext_stap_scan_test — the extended STAP host scan interface, with the
// tb_top host segment behind it, follows the PTAP 3DCR select: its controls
// pulse and the segment returns the chain; under the stap_host disable the
// controls stay quiet and the last STAP's scan-out returns instead; both
// recover without reset (looped runner with per-pass family evidence).

class dtp_ext_stap_scan_test extends dtp_base_test;
  `uvm_component_utils(dtp_ext_stap_scan_test)

  function new(string name = "dtp_ext_stap_scan_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function bit stap_host_segment_attach();
    return 1'b1;
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
