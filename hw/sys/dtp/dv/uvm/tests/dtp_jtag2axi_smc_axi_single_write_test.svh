// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_single_write_test — the `single_write` SMC fabric
// JTAG2AXI scenario: directed size/strobe sweep plus seeded random cases,
// every write intent-armed so the shared AXI scoreboard proves address,
// data, and strobes on the bus.

class dtp_jtag2axi_smc_axi_single_write_test extends dtp_base_test;
    `uvm_component_utils(dtp_jtag2axi_smc_axi_single_write_test)

    function new(string name = "dtp_jtag2axi_smc_axi_single_write_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_smc_axi_cfg.require_checks = 1'b1;
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-COMPLETION");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-NONVAC");
    endfunction

    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        dtp_jtag2axi_smc_axi_wr_test_seq seq =
            dtp_jtag2axi_smc_axi_wr_test_seq::type_id::create("seq");
        seq.scenario = "single_write";
        return seq;
    endfunction

    virtual function string specific_loops_plusarg();
        return "DTP_JTAG2AXI_SMC_AXI_SINGLE_WRITE_TEST_LOOPS";
    endfunction

    virtual function string group_loops_plusarg();
        return "DTP_JTAG2AXI_TEST_LOOPS";
    endfunction

    virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
        dtp_jtag2axi_smc_axi_wr_test_seq wr;
        super.plumb_scenario_seq(seq);
        if (!$cast(wr, seq))
            `uvm_fatal(get_type_name(), "scenario sequence type mismatch")
        wr.axi_cfg       = m_env.m_smc_axi_cfg;
        wr.axi_evidence  = m_env.m_smc_axi_env.m_checker;
        wr.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
        wr.slave_seq     = m_env.m_smc_axi_slave_agent.seq;
    endfunction

endclass : dtp_jtag2axi_smc_axi_single_write_test
