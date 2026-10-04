// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Single-cycle system-reset pulse while a write is held on the AW
// channel of every bridge, with the bridge FSM observed mid-flight
// through dtp_tb_if, then a second pulse once the first clear has
// completed; the FSM's return to IDLE, both CDC TCK-side clears, the
// absence of an escaped write, and the recovery status are recorded per
// bridge. Then a SINGLE_OP read or write held on the fabric by a responder
// READY stall across a TCK-side clear (TRST, or a TMS walk into
// Test-Logic-Reset), released inside the clear, after it, after it with a
// request of the new session queued behind it, or a swept number of system
// cycles around the TRST assertion; the held request lands exactly once,
// its response never reaches the JTAG side, the queued request completes
// after it with its own status, and the next operation reports its own
// response.

class dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test)

  function new(string name = "dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "cdc_clear_abort_narrow_reset_mid_xaction";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_CDC_CLEAR_ABORT_NARROW_RESET_MID_XACTION_TEST_LOOPS";
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
    ids.push_back(DtpJ2aAbortMidFlightCheckId);
    ids.push_back(DtpJ2aAbortFsmCheckId);
    ids.push_back(DtpJ2aCdcClearCheckId);
    ids.push_back(DtpJ2aAbortEscapeCheckId);
    ids.push_back(DtpJ2aAbortRecoveryCheckId);
    ids.push_back(DtpJ2aOrphanDrainCheckId);
    ids.push_back(DtpJ2aOrphanDiscardCheckId);
    ids.push_back(DtpJ2aOrphanOrderCheckId);
  endfunction

endclass : dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test
