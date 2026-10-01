// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_axi_channel_skew_test — AW-first/W-first skewed writes, deferred BREADY, and an RREADY-hold read
// (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_xtrig_axi_channel_skew_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_axi_channel_skew_test)

  function new(string name = "dtp_xtrig_axi_channel_skew_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_csr_test_seq seq = dtp_xtrig_csr_test_seq::type_id::create("seq");
    seq.scenario = "axi_channel_skew";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_AXI_CHANNEL_SKEW_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_axi_channel_skew_test
