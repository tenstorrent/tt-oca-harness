// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_3dcr_tms_hold_test — per-STAP, per-polarity select/deselect flow in a seeded order: the
// deselected port parks its host TMS at the stored TMS_HOLD for a whole scan,
// never drives tdo_oen, and its 3DCR reads back through the chain
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_3dcr_tms_hold_test extends dtp_base_test;
  `uvm_component_utils(dtp_3dcr_tms_hold_test)

  function new(string name = "dtp_3dcr_tms_hold_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
    seq.scenario = "tms_hold";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_3DCR_TMS_HOLD_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_3dcr_tms_hold_test
