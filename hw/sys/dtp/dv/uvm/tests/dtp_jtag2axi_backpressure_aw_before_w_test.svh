// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_backpressure_aw_before_w_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// WREADY stalled behind an accepted AW on every bridge: each checked
// write completes SUCCESS, produced a real AW request pulse, and its
// observed bus fields match the stimulus intent.

class dtp_jtag2axi_backpressure_aw_before_w_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_backpressure_aw_before_w_test)

  function new(string name = "dtp_jtag2axi_backpressure_aw_before_w_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "backpressure_aw_before_w";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_BACKPRESSURE_AW_BEFORE_W_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-J2A-STALL-FSM");
    ids.push_back("CHK-J2A-STALL-BUSY");
    ids.push_back("CHK-J2A-STALL-HOLD");
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-WMEM");
  endfunction

endclass : dtp_jtag2axi_backpressure_aw_before_w_test
