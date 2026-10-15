// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared base for the cross-bridge JTAG2AXI robustness tests: arms the
// baseline evidence contract on every bridge's passive recorder through the
// test cfg (so a silent bridge fails at finalization); dtp_base_test plumbs
// every bridge's evidence bundle. Concrete tests name the scenario, the
// specific loops knob, and any scenario-specific required evidence IDs.

class dtp_jtag2axi_robustness_base_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_robustness_base_test)

  function new(string name = "dtp_jtag2axi_robustness_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function string scenario_name();
    return "";
  endfunction

  // Baseline per-port evidence contract; concrete tests extend it with
  // super.add_required_axi_ids(ids) plus their scenario-specific IDs.
  virtual function void add_required_axi_ids(ref string ids[$]);
    ids.push_back("CHK-AXI-RESP");
    ids.push_back("CHK-AXI-COMPLETION");
    ids.push_back("CHK-AXI-NONVAC");
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    string ids[$];
    super.configure_test_cfg(cfg);
    add_required_axi_ids(ids);
    cfg.require_axi_ids("smc_axi", ids);
    cfg.require_axi_ids("smc_otp", ids);
    cfg.require_axi_ids("sep_otp", ids);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_robustness_test_seq seq = dtp_jtag2axi_robustness_test_seq::type_id::create(
        {scenario_name(), "_seq"}
    );
    seq.scenario = scenario_name();
    return seq;
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_robustness_base_test
