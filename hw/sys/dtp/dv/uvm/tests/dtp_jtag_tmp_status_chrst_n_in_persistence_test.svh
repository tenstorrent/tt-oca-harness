// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_tmp_status_chrst_n_in_persistence_test — TMP persistence must survive a seeded-width chip-reset pulse
// while the TAP stays accessible
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_jtag_tmp_status_chrst_n_in_persistence_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag_tmp_status_chrst_n_in_persistence_test)

  function new(string name = "dtp_jtag_tmp_status_chrst_n_in_persistence_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG_TMP_STATUS_CHRST_N_IN_PERSISTENCE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_DEBUG_TDR_TEST_LOOPS";
  endfunction

endclass : dtp_jtag_tmp_status_chrst_n_in_persistence_test
