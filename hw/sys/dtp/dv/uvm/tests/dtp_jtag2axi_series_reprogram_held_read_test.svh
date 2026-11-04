// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_series_reprogram_held_read_test — cross-bridge robustness
// scenario iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// SERIES_CTRL reprogrammed while a series read waits for its held R: a plain
// read with the new programming's issue scans queued behind it, at a seeded
// depth below the read pipeline depth and at that depth, and a
// WITH_ERROR_STATUS read. Then an incrementing READ series at the read
// pipeline depth, whose captures that are not the pending marker return the
// series' words in order.

class dtp_jtag2axi_series_reprogram_held_read_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_series_reprogram_held_read_test)

  function new(string name = "dtp_jtag2axi_series_reprogram_held_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "series_reprogram_held_read";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-J2A-SERIES-ADDR");
    ids.push_back("CHK-J2A-FAULT-STATUS");
    ids.push_back("CHK-AXI-RDATA");
    ids.push_back(DtpJ2aStatusBitCheckId);
    ids.push_back(DtpJ2aBusReqCheckId);
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SERIES_REPROGRAM_HELD_READ_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_series_reprogram_held_read_test
