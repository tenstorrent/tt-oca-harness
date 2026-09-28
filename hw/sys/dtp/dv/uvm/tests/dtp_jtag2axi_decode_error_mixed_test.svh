// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_decode_error_mixed_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Clean and DECERR-faulted accesses interleaved on every bridge: a good
// checked write, a DECERR read and a DECERR write at a neighbouring slot,
// then a good checked read proves the clean slot and its status are
// unaffected.

class dtp_jtag2axi_decode_error_mixed_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_decode_error_mixed_test)

  function new(string name = "dtp_jtag2axi_decode_error_mixed_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "decode_error_mixed";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_DECODE_ERROR_MIXED_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-AXI-ERR-INJ");
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-RADDR");
    ids.push_back("CHK-AXI-RDATA");
  endfunction

endclass : dtp_jtag2axi_decode_error_mixed_test
