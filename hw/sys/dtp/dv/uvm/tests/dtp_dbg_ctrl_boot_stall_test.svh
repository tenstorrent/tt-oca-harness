// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_dbg_ctrl_boot_stall_test — DEBUG_CONTROL boot-stall matrix, independence from the override,
// and independence from the clock-stop bits
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_dbg_ctrl_boot_stall_test extends dtp_base_test;
  `uvm_component_utils(dtp_dbg_ctrl_boot_stall_test)

  function new(string name = "dtp_dbg_ctrl_boot_stall_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_dbg_ctrl_boot_stall_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_DBG_CTRL_BOOT_STALL_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_DEBUG_TDR_TEST_LOOPS";
  endfunction

endclass : dtp_dbg_ctrl_boot_stall_test
