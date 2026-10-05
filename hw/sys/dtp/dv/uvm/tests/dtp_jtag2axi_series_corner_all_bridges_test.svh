// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_series_corner_all_bridges_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Series corner coverage on every bridge: incrementing and fixed-address
// write series with their SERIES_CTRL address captures, a faulted beat whose
// status holds until SERIES_CTRL.reset, and the three bridges' beats
// interleaved. Then every entry of each bridge's CDC FIFOs filled at least
// twice in one TAP session by checked writes and reads with seeded
// addresses, sizes, data and one SLVERR or DECERR per entry; a TAP reset and
// a system reset with every entry holding its payload, each followed by its
// CDC clear, the SINGLE_OP status back at its reset value, and a recovery
// write and read on every bridge.

class dtp_jtag2axi_series_corner_all_bridges_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_series_corner_all_bridges_test)

  function new(string name = "dtp_jtag2axi_series_corner_all_bridges_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "series_corner_all_bridges";
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-RESET-COUNT"});
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-J2A-SERIES-ADDR");
    ids.push_back("CHK-J2A-FAULT-STATUS");
    ids.push_back("CHK-AXI-ERR-INJ");
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-RADDR");
    ids.push_back("CHK-AXI-RDATA");
    ids.push_back("CHK-AXI-WMEM");
    ids.push_back(DtpJ2aErrRdataCheckId);
    ids.push_back(DtpJ2aCdcClearCheckId);
    ids.push_back(DtpJ2aAbortFsmCheckId);
    ids.push_back(DtpJ2aAbortRecoveryCheckId);
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SERIES_CORNER_ALL_BRIDGES_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_series_corner_all_bridges_test
