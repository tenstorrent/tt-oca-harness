// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_por_independence_test — POR-only TAP reset: runs
// dtp_jtag_trst_por_independence_test_seq at the looped floor, each pass
// proving a power-on reset forces Test-Logic-Reset with TRST_N deasserted
// throughout and that IDCODE reads back after recovery. The pulse the
// sequence drives records CHK-RESET-COUNT on the env recorder.

class dtp_jtag_trst_por_independence_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_trst_por_independence_test)

  function new(string name = "dtp_jtag_trst_por_independence_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR", "CHK-RESET-COUNT"});
    cfg.require_feature(DtpFeatureIdcode);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return
        dtp_jtag_trst_por_independence_test_seq::type_id::create("jtag_trst_por_independence_seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_TRST_POR_INDEPENDENCE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_BASIC_JTAG_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_trst_por_independence_test
