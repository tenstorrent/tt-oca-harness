// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ctm_wire_or_cla_to_cla_test — seeded cla_to_cla wire-OR route plus a
// two-source overlap onto one shared destination (looped runner with per-pass
// CHK-XTRIG-* evidence).

class dtp_ctm_wire_or_cla_to_cla_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_ctm_wire_or_cla_to_cla_test)

  function new(string name = "dtp_ctm_wire_or_cla_to_cla_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ctm_route_test_seq seq = dtp_ctm_route_test_seq::type_id::create("seq");
    seq.scenario = "ctm_wire_or_cla_to_cla";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_CTM_WIRE_OR_CLA_TO_CLA_TEST_LOOPS";
  endfunction

endclass : dtp_ctm_wire_or_cla_to_cla_test
