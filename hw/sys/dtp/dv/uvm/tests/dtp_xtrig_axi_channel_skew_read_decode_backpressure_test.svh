// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_axi_channel_skew_read_decode_backpressure_test — unmapped reads return DECERR with stable RDATA/RRESP under RREADY backpressure
// (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_xtrig_axi_channel_skew_read_decode_backpressure_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_axi_channel_skew_read_decode_backpressure_test)

  function new(string name = "dtp_xtrig_axi_channel_skew_read_decode_backpressure_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // The scenario reads only the unmapped decode space, so the readback
  // shadow never compares; the decode-error response is the feature under
  // test.
  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.set_required_features('{DtpFeatureXtrigDecode});
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_csr_test_seq seq = dtp_xtrig_csr_test_seq::type_id::create("seq");
    seq.scenario = "axi_channel_skew_read_decode_backpressure";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_AXI_CHANNEL_SKEW_READ_DECODE_BACKPRESSURE_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_axi_channel_skew_read_decode_backpressure_test
