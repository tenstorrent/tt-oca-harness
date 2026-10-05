// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_id_match_test — response-ID parity contract with the cocotb twin: every
// blocking master result exposes the issued AWID/ARID and a BID/RID sampled
// live from the response handshake (RLAST beat for bursts), proven full-
// stack against the shared fault slave with the passive env scoring the
// same wires. Required CHK-* evidence on both the scenario checker and the
// wire-level scoreboard.

class ocah_axi_id_match_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_id_match_test)

  function new(string name = "ocah_axi_id_match_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-ID-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-ID-RD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-ID-DEFAULT");
    m_env.m_checker.required_ids.push_back("CHK-AXI-ID-BURST-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-ID-BURST-RD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-RDBK");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BACKDOOR-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BURST-RDATA");
    m_env.m_axi_cfg.require_checks = 1'b1;
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RADDR");
  endfunction

  task run_phase(uvm_phase phase);
    ocah_axi_id_match_test_seq seq;
    phase.raise_objection(this, "ocah_axi_id_match_test running");
    seq = ocah_axi_id_match_test_seq::type_id::create("seq");
    seq.evidence  = m_env.m_checker;
    seq.axi_cfg   = m_env.m_axi_cfg;
    seq.slave_seq = m_env.m_slave_agent.seq;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_id_match_test done");
  endtask

endclass : ocah_axi_id_match_test
