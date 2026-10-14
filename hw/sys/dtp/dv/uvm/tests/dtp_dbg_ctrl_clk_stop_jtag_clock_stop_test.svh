// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test — JTAG_CLOCK_STOP
// asserts/releases stop_clks repeatably with the CLA path untouched (looped
// runner with per-pass family evidence).

class dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test extends dtp_base_test;
  `uvm_component_utils(dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test)

  function new(string name = "dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_DBG_CTRL_CLK_STOP_JTAG_CLOCK_STOP_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_DEBUG_TDR_TEST_LOOPS";
  endfunction

endclass : dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test
