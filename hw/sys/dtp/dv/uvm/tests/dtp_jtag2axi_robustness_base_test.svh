// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared base for the cross-bridge JTAG2AXI robustness tests: arms the
// baseline evidence contract on every bridge's passive recorder through the
// test cfg (so a silent bridge fails at finalization) and plumbs the
// per-target evidence bundles for all three bridges (smc_axi, smc_otp,
// sep_otp) into the robustness sequence; the responders come from the
// virtual sequencer. Concrete tests name the scenario, the specific loops
// knob, and any scenario-specific required evidence IDs.

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

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_robustness_test_seq rob_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(rob_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_robustness_test_seq")
    // Index order mirrors the sequence's target order:
    // smc_axi, smc_otp, sep_otp.
    rob_seq.target_cfgs       = '{m_env.m_smc_axi_cfg,
                                      m_env.m_smc_otp_axi_cfg,
                                      m_env.m_sep_otp_axi_cfg};
    rob_seq.target_evidence   = '{m_env.m_smc_axi_env.m_checker,
                                      m_env.m_smc_otp_axi_env.m_checker,
                                      m_env.m_sep_otp_axi_env.m_checker};
    rob_seq.target_ref_models = '{m_env.m_smc_axi_env.m_ref_model,
                                      m_env.m_smc_otp_axi_env.m_ref_model,
                                      m_env.m_sep_otp_axi_env.m_ref_model};
  endfunction

endclass : dtp_jtag2axi_robustness_base_test
