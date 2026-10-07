// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_wire_or_test — CTP wire-OR pulse stretching, busy-clear status,
// and external-to-internal sync (looped runner with per-pass CHK-XTRIG-*
// evidence).

class dtp_xtrig_wire_or_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_wire_or_test)

  function new(string name = "dtp_xtrig_wire_or_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_route_test_seq seq = dtp_xtrig_route_test_seq::type_id::create("seq");
    seq.scenario = "wire_or";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_WIRE_OR_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_wire_or_test
