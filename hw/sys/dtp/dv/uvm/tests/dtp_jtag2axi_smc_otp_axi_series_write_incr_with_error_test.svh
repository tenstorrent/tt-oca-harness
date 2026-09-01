// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test — the
// `series_write_incr_with_error` SMC OTP AXI-Lite JTAG2AXI scenario:
// SERIES_DATA_WITH_ERROR_STATUS write mode with a mixed per-beat increment
// pattern; memory and the post-stream SERIES_CTRL address prove each beat's
// increment decision took effect.

class dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test extends dtp_base_test;
    `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test)

    function new(string name = "dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_smc_otp_axi_cfg.require_checks = 1'b1;
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-COMPLETION");
        m_env.m_smc_otp_axi_cfg.required_ids.push_back("CHK-AXI-NONVAC");
    endfunction

    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        dtp_jtag2axi_otp_axi_test_seq seq =
            dtp_jtag2axi_otp_axi_test_seq::type_id::create("smc_otp_series_write_incr_with_error_seq");
        seq.target_name = "smc_otp";
        seq.scenario    = "series_write_incr_with_error";
        return seq;
    endfunction

    virtual function string specific_loops_plusarg();
        return "DTP_JTAG2AXI_SMC_OTP_AXI_SERIES_WRITE_INCR_WITH_ERROR_TEST_LOOPS";
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

endclass : dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test
