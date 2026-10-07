// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_wire_or_bus_test — several CTPs on one shared wire-OR wire: the transmitter's own
// pull, a chiplet's pull, and the two merged reach every member once at the receive latency
// (looped runner with per-pass CHK-XTRIG-* evidence).

class dtp_xtrig_wire_or_bus_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_wire_or_bus_test)

  function new(string name = "dtp_xtrig_wire_or_bus_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_route_test_seq seq = dtp_xtrig_route_test_seq::type_id::create("seq");
    seq.scenario = "wire_or_bus";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_WIRE_OR_BUS_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_wire_or_bus_test
