// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base test for the xtrig group. The xtrig scenarios drive the CSR AXI-Lite
// port through the shared VIP master agent (reusable CSR sequences on the
// virtual sequencer's m_xtrig_seqr handle) and the cross-trigger pins
// through dtp_xtrig_if; no JTAG traffic at all. The scoreboard feature the
// group must exercise is therefore xtrig_csr (the CSR shadow predictor on
// the passive XTRIG monitor stream), and the TAP FSM checker's zero-cycle
// activity demand is lifted (any TCK activity that does occur is still
// checked per cycle). Loop-count and seed resolution is the standard
// dtp_base_test contract with the group knob +DTP_XTRIG_TEST_LOOPS.

class dtp_xtrig_base_test extends dtp_base_test;
  `uvm_component_utils(dtp_xtrig_base_test)

  function new(string name = "dtp_xtrig_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.jtag_activity_required = 1'b0;
    cfg.set_required_features('{DtpFeatureXtrigCsr});
  endfunction

  virtual function string group_loops_knob();
    return "DTP_XTRIG_TEST_LOOPS";
  endfunction

endclass : dtp_xtrig_base_test
