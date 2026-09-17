// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_decode_error_decerr_write_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// One-shot DECERR write injection by every bridge's responder (the DTP
// boundary has no address decoder): the JTAG status reports DECERR, the
// injected response is classified EXPECTED, the errored slot keeps its
// prior word, and an OKAY recovery write with memory-vs-intent compare
// follows.

class dtp_jtag2axi_decode_error_decerr_write_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_decode_error_decerr_write_test)

  function new(string name = "dtp_jtag2axi_decode_error_decerr_write_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "decode_error_decerr_write";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_DECODE_ERROR_DECERR_WRITE_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-AXI-ERR-INJ");
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-WMEM");
  endfunction

endclass : dtp_jtag2axi_decode_error_decerr_write_test
