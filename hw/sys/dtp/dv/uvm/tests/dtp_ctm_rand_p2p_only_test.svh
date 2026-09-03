// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ctm_rand_p2p_only_test — seeded random point-to-point route mix
// (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_ctm_rand_p2p_only_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_ctm_rand_p2p_only_test)

  function new(string name = "dtp_ctm_rand_p2p_only_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ctm_route_test_seq seq = dtp_ctm_route_test_seq::type_id::create("seq");
    seq.scenario = "ctm_rand_p2p_only";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_CTM_RAND_P2P_ONLY_TEST_LOOPS";
  endfunction

endclass : dtp_ctm_rand_p2p_only_test
