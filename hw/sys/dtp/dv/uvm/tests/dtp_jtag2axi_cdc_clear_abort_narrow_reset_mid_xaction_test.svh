// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test — cross-bridge robustness scenario
// iterating all three JTAG2AXI bridges (smc_axi, smc_otp, sep_otp).
// Single-cycle system-reset pulse after a write issued against a
// stalled AW channel on every bridge; a recovery write with
// memory-vs-intent compare proves the CDC clear/abort path leaves no
// stuck state.

class dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test extends dtp_jtag2axi_robustness_base_test;
  `uvm_component_utils(dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test)

  function new(string name = "dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "cdc_clear_abort_narrow_reset_mid_xaction";
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG2AXI_CDC_CLEAR_ABORT_NARROW_RESET_MID_XACTION_TEST_LOOPS";
  endfunction

  virtual function void add_required_axi_ids(ocah_axi_config cfg);
    super.add_required_axi_ids(cfg);
    cfg.required_ids.push_back("CHK-AXI-WADDR");
    cfg.required_ids.push_back("CHK-AXI-WDATA");
    cfg.required_ids.push_back("CHK-AXI-STRB");
    cfg.required_ids.push_back("CHK-AXI-WMEM");
  endfunction

endclass : dtp_jtag2axi_cdc_clear_abort_narrow_reset_mid_xaction_test
