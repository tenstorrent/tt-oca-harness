// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_single_write_read_test: the
// same single-op scenario on the SMC fabric AXI4 manager port (132-bit wide
// TDR scans, 64-bit data, ID-tagged bursts observed by the shared monitor).

class dtp_jtag2axi_smc_axi_single_write_read_test extends dtp_base_test;
    `uvm_component_utils(dtp_jtag2axi_smc_axi_single_write_read_test)

    function new(string name = "dtp_jtag2axi_smc_axi_single_write_read_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_smc_axi_cfg.require_checks = 1'b1;
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-ERR-INJ");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RADDR");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AW");
        m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AR");
    endfunction

    task run_phase(uvm_phase phase);
        dtp_jtag2axi_single_op_seq seq;
        phase.raise_objection(this, "dtp_jtag2axi_smc_axi_single_write_read_test running");
        seq = dtp_jtag2axi_single_op_seq::type_id::create("seq");
        seq.tb_vif        = m_env.tb_vif;
        seq.target_name   = "smc_axi";
        seq.axi_cfg       = m_env.m_smc_axi_cfg;
        seq.axi_evidence  = m_env.m_smc_axi_env.m_checker;
        seq.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
        seq.slave_seq     = m_env.m_smc_axi_slave_agent.seq;
        seq.start(m_env.m_jtag_env.m_sequencer);
        phase.drop_objection(this, "dtp_jtag2axi_smc_axi_single_write_read_test done");
    endtask

endclass : dtp_jtag2axi_smc_axi_single_write_read_test
