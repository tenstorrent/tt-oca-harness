// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_backpressure_abort_at_data_w_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// System-reset pulse while a write is held on the W channel of every
// bridge, with the bridge FSM observed mid-flight through dtp_tb_if; the
// FSM's return to IDLE, the CDC's TCK-side clear, the absence of an
// escaped write, and the recovery status are recorded per bridge.

class dtp_jtag2axi_backpressure_abort_at_data_w_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_backpressure_abort_at_data_w_test)

  function new(string name = "dtp_jtag2axi_backpressure_abort_at_data_w_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "backpressure_abort_at_data_w";
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_BACKPRESSURE_ABORT_AT_DATA_W_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ref string ids[$]);
    super.add_required_axi_ids(ids);
    ids.push_back("CHK-AXI-WADDR");
    ids.push_back("CHK-AXI-WDATA");
    ids.push_back("CHK-AXI-STRB");
    ids.push_back("CHK-AXI-WMEM");
    ids.push_back(DtpJ2aAbortMidFlightCheckId);
    ids.push_back(DtpJ2aAbortFsmCheckId);
    ids.push_back(DtpJ2aCdcClearCheckId);
    ids.push_back(DtpJ2aAbortEscapeCheckId);
    ids.push_back(DtpJ2aAbortRecoveryCheckId);
  endfunction

endclass : dtp_jtag2axi_backpressure_abort_at_data_w_test
