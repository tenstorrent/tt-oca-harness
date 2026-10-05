// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_decode_error_decerr_read_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// One-shot DECERR read injection by every bridge's responder (the DTP
// boundary has no address decoder): the JTAG status reports DECERR, the
// injected response is classified EXPECTED, the SINGLE_OP capture returns
// the errored beat's RDATA and not the preloaded word (CHK-J2A-ERR-RDATA),
// and an OKAY recovery read of a preloaded value follows.

class dtp_jtag2axi_decode_error_decerr_read_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_decode_error_decerr_read_test)

  function new(string name = "dtp_jtag2axi_decode_error_decerr_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "decode_error_decerr_read";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_DECODE_ERROR_DECERR_READ_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-AXI-ERR-INJ");
    ids.push_back("CHK-AXI-RADDR");
    ids.push_back("CHK-AXI-RDATA");
    ids.push_back("CHK-J2A-ERR-RDATA");
  endfunction

endclass : dtp_jtag2axi_decode_error_decerr_read_test
