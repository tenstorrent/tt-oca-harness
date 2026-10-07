// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_axi_channel_skew_demux_aw_lock_release_test — skewed write pairs across CTP and CTM
// registers proving the demux holds the second AW until the first W passes (looped runner with
// per-pass CHK-XTRIG-* evidence).

class dtp_xtrig_axi_channel_skew_demux_aw_lock_release_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_axi_channel_skew_demux_aw_lock_release_test)

  function new(string name = "dtp_xtrig_axi_channel_skew_demux_aw_lock_release_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_csr_test_seq seq = dtp_xtrig_csr_test_seq::type_id::create("seq");
    seq.scenario = "axi_channel_skew_demux_aw_lock_release";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_AXI_CHANNEL_SKEW_DEMUX_AW_LOCK_RELEASE_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_axi_channel_skew_demux_aw_lock_release_test
