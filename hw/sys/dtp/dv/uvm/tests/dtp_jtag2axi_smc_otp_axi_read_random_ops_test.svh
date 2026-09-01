// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_read_random_ops_test — the `read_random_ops` SMC
// fabric JTAG2AXI scenario: randomized single reads (address/size/payload)
// of backdoor-preloaded responder memory, every returned value checked in
// the sequence and every observed read compared by the shared passive env.

class dtp_jtag2axi_smc_otp_axi_read_random_ops_test extends dtp_base_test;
    `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_read_random_ops_test)

    function new(string name = "dtp_jtag2axi_smc_otp_axi_read_random_ops_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_smc_otp_axi_cfg.require_checks = 1'b1;
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RADDR");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-COMPLETION");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-NONVAC");
    endfunction

    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        dtp_jtag2axi_otp_axi_test_seq seq =
            dtp_jtag2axi_otp_axi_test_seq::type_id::create("smc_otp_read_random_ops_seq");
        seq.target_name = "smc_otp";
        seq.scenario    = "read_random_ops";
        return seq;
    endfunction

    virtual function string specific_loops_plusarg();
        return "DTP_JTAG2AXI_SMC_OTP_AXI_READ_RANDOM_OPS_TEST_LOOPS";
    endfunction

    virtual function string group_loops_plusarg();
        return "DTP_JTAG2AXI_TEST_LOOPS";
    endfunction

    virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
        dtp_jtag2axi_otp_axi_test_seq t_seq;
        super.plumb_scenario_seq(seq);
        if (!$cast(t_seq, seq))
            `uvm_fatal(get_type_name(),
                "scenario sequence is not a dtp_jtag2axi_otp_axi_test_seq")
        t_seq.axi_cfg       = m_env.m_smc_otp_axi_cfg;
        t_seq.axi_evidence  = m_env.m_smc_otp_axi_env.m_checker;
        t_seq.axi_ref_model = m_env.m_smc_otp_axi_env.m_ref_model;
        t_seq.slave_seq     = m_env.m_smc_otp_slave_agent.seq;
    endfunction

endclass : dtp_jtag2axi_smc_otp_axi_read_random_ops_test
