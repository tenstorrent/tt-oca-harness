// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared base for the cross-bridge JTAG2AXI robustness tests: plumbs the
// per-target handle bundles for all three bridges (smc_axi, smc_otp,
// sep_otp) into the robustness sequence and arms the baseline evidence
// contract on every port recorder, so a silent bridge fails at
// finalization. Concrete tests name the scenario, the specific loops
// plusarg, and any scenario-specific required evidence IDs.

class dtp_jtag2axi_robustness_base_test extends dtp_base_test;
    `uvm_component_utils(dtp_jtag2axi_robustness_base_test)

    function new(string name = "dtp_jtag2axi_robustness_base_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    // Scenario selector consumed by create_scenario_seq().
    virtual function string scenario_name();
        return "";
    endfunction

    // Baseline per-port evidence contract; concrete tests extend it with
    // super.add_required_axi_ids(cfg) plus their scenario-specific IDs.
    virtual function void add_required_axi_ids(ocah_axi_config cfg);
        cfg.require_checks = 1'b1;
        cfg.required_ids.push_back("CHK-AXI-RESP");
        cfg.required_ids.push_back("CHK-AXI-COMPLETION");
        cfg.required_ids.push_back("CHK-AXI-NONVAC");
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        add_required_axi_ids(m_env.m_smc_axi_cfg);
        add_required_axi_ids(m_env.m_smc_otp_axi_cfg);
        add_required_axi_ids(m_env.m_sep_otp_axi_cfg);
    endfunction

    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        dtp_jtag2axi_robustness_test_seq seq =
            dtp_jtag2axi_robustness_test_seq::type_id::create(
                {scenario_name(), "_seq"});
        seq.scenario = scenario_name();
        return seq;
    endfunction

    virtual function string group_loops_plusarg();
        return "DTP_JTAG2AXI_TEST_LOOPS";
    endfunction

    virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
        dtp_jtag2axi_robustness_test_seq rob_seq;
        super.plumb_scenario_seq(seq);
        if (!$cast(rob_seq, seq))
            `uvm_fatal(get_type_name(),
                "scenario sequence is not a dtp_jtag2axi_robustness_test_seq")
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
        rob_seq.target_slaves     = '{m_env.m_smc_axi_slave_agent.seq,
                                      m_env.m_smc_otp_slave_agent.seq,
                                      m_env.m_sep_otp_slave_agent.seq};
    endfunction

endclass : dtp_jtag2axi_robustness_base_test
