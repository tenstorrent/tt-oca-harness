// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ctm_p2p_ctp_to_ctp_test — three seeded ctp_to_ctp point-to-point routes
// with full req/ack handshakes (looped runner with per-pass CHK-XTRIG-*
// evidence).

class dtp_ctm_p2p_ctp_to_ctp_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_ctm_p2p_ctp_to_ctp_test)

  function new(string name = "dtp_ctm_p2p_ctp_to_ctp_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ctm_route_test_seq seq = dtp_ctm_route_test_seq::type_id::create("seq");
    seq.scenario = "ctm_p2p_ctp_to_ctp";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_CTM_P2P_CTP_TO_CTP_TEST_LOOPS";
  endfunction

endclass : dtp_ctm_p2p_ctp_to_ctp_test
