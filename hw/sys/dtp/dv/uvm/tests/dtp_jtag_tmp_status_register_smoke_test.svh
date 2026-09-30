// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_tmp_status_register_smoke_test — TMP_STATUS reset/read smoke with shuffled shift-value sweep,
// CLAMP_HOLD persistence entry, and a final IDCODE read that returns the configured IDCODE
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_jtag_tmp_status_register_smoke_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_tmp_status_register_smoke_test)

  function new(string name = "dtp_jtag_tmp_status_register_smoke_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_tmp_status_register_smoke_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_TMP_STATUS_REGISTER_SMOKE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_DEBUG_TDR_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_tmp_status_register_smoke_test
