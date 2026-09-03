// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_scan_dbg_disable_matrix_test — the debug-disable matrix over the
// eight scan-side gate fields: one-hot, boundary, and seeded multi-hot
// rows with temporal-window and chain-readback outcome proofs. One matrix
// pass carries 16 seeded rows (1 all_clear + 8 one-hot + 6 multi-hot +
// 1 all_disabled), meeting the 16-iteration floor in a single pass.

class dtp_scan_dbg_disable_matrix_test extends dtp_base_test;
  `uvm_component_utils(dtp_scan_dbg_disable_matrix_test)

  function new(string name = "dtp_scan_dbg_disable_matrix_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    dtp_dbg_disable_scan_matrix_test_seq seq =
            dtp_dbg_disable_scan_matrix_test_seq::type_id::create("seq");
    int unsigned rows;
    if ($value$plusargs("DTP_DBG_DISABLE_MULTI_HOT_ROWS=%d", rows)) seq.multi_hot_rows = rows;
    return seq;
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_SCAN_DBG_DISABLE_MATRIX_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_SCAN_TEST_LOOPS";
  endfunction

endclass : dtp_scan_dbg_disable_matrix_test
