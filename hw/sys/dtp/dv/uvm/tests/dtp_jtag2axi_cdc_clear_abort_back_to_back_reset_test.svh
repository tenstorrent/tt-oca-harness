// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// A SINGLE_OP write completed with SLVERR, then two adjacent
// system-reset pulses with seeded spacing on every bridge; the SLVERR
// survives the resets, and recovery write and read accesses prove the
// bridges come back clean after repeated CDC clears.

class dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test)

  function new(string name = "dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "cdc_clear_abort_back_to_back_reset";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_CDC_CLEAR_ABORT_BACK_TO_BACK_RESET_TEST_LOOPS";
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_jtag_ids('{"CHK-RESET-COUNT"});
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-AXI-ERR-INJ");
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-RADDR");
    ids.push_back("CHK-AXI-RDATA");
    ids.push_back("CHK-AXI-WMEM");
    ids.push_back(DtpJ2aCdcClearCheckId);
    ids.push_back(DtpJ2aAbortRecoveryCheckId);
  endfunction

endclass : dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test
