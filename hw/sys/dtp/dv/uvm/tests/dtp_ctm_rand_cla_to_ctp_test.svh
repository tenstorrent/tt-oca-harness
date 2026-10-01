// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ctm_rand_cla_to_ctp_test — seeded random internal-to-CTP route mix
// (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_ctm_rand_cla_to_ctp_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_ctm_rand_cla_to_ctp_test)

  function new(string name = "dtp_ctm_rand_cla_to_ctp_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ctm_route_test_seq seq = dtp_ctm_route_test_seq::type_id::create("seq");
    seq.scenario = "ctm_rand_cla_to_ctp";
    seq.total_passes = loop_count(specific_loops_knob(), group_loops_knob(), default_loops());
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_CTM_RAND_CLA_TO_CTP_TEST_LOOPS";
  endfunction

endclass : dtp_ctm_rand_cla_to_ctp_test
