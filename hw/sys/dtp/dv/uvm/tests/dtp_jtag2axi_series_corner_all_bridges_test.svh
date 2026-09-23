// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_series_corner_all_bridges_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Series corner coverage on every bridge: incrementing and fixed-address
// write series with their SERIES_CTRL address captures, a faulted beat whose
// status holds until SERIES_CTRL.reset, and the three bridges' beats
// interleaved.

class dtp_jtag2axi_series_corner_all_bridges_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_series_corner_all_bridges_test)

  function new(string name = "dtp_jtag2axi_series_corner_all_bridges_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "series_corner_all_bridges";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-J2A-SERIES-ADDR");
    ids.push_back("CHK-J2A-FAULT-STATUS");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SERIES_CORNER_ALL_BRIDGES_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_series_corner_all_bridges_test
