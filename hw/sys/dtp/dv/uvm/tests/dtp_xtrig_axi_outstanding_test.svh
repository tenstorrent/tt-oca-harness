// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_xtrig_axi_outstanding_test — bursts of reads and of writes in flight with the responses held
// stall the CSR port and reach every crossbar subordinate, a write, a read and a second write to
// one CTP engage the demux AW lock, and every access answers DECERR exactly when its word is
// unmapped (looped runner with per-pass CHK-XTRIG-* evidence, 16-pass floor).

class dtp_xtrig_axi_outstanding_test extends dtp_xtrig_base_test;
  `uvm_component_utils(dtp_xtrig_axi_outstanding_test)

  function new(string name = "dtp_xtrig_axi_outstanding_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // The pipelines read and write registers and unmapped words; the readback shadow judges the
  // mapped reads' data and the decode feature judges every response.
  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.set_required_features('{DtpFeatureXtrigCsr, DtpFeatureXtrigDecode});
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_xtrig_csr_test_seq seq = dtp_xtrig_csr_test_seq::type_id::create("seq");
    seq.scenario = "axi_outstanding";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_XTRIG_AXI_OUTSTANDING_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_axi_outstanding_test
