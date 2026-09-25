// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_backpressure_long_stall_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Long bounded AW+W READY stalls sized in status-poll units on every
// bridge (BUSY_OR_FULL observed before the settled status), a
// stalled-AR read of a preloaded value, then zero-strobe and
// memory-window-boundary corner writes once the stalls are cleared.

class dtp_jtag2axi_backpressure_long_stall_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_backpressure_long_stall_test)

  function new(string name = "dtp_jtag2axi_backpressure_long_stall_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "backpressure_long_stall";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_BACKPRESSURE_LONG_STALL_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-J2A-STALL-FSM");
    ids.push_back("CHK-J2A-STALL-BUSY");
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-RADDR");
    ids.push_back("CHK-AXI-RDATA");
  endfunction

endclass : dtp_jtag2axi_backpressure_long_stall_test
