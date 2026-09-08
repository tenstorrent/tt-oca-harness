// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_ctm_reset_p2p_mode_test — routes established, system reset, select defaults with quiet pins, fresh routes recover
// (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_ctm_reset_p2p_mode_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_ctm_reset_p2p_mode_test)

  function new(string name = "dtp_ctm_reset_p2p_mode_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_ctm_route_test_seq seq = dtp_ctm_route_test_seq::type_id::create("seq");
    seq.scenario = "ctm_reset_p2p_mode";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_CTM_RESET_P2P_MODE_TEST_LOOPS";
  endfunction

endclass : dtp_ctm_reset_p2p_mode_test
