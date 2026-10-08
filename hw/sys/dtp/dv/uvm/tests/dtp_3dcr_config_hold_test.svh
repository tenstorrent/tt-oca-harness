// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_3dcr_config_hold_test — per-STAP PTAP and STAP 3DCR CONFIG_HOLD
// sub-cases in a seeded order (hold=1 across TLR preserves, hold=0 across TLR
// clears, TRST clears), each read back through composed chain scans (looped
// runner with per-pass family evidence).

class dtp_3dcr_config_hold_test extends dtp_base_test;
  `uvm_component_utils(dtp_3dcr_config_hold_test)

  function new(string name = "dtp_3dcr_config_hold_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
    seq.scenario = "config_hold";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_3DCR_CONFIG_HOLD_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_3dcr_config_hold_test
