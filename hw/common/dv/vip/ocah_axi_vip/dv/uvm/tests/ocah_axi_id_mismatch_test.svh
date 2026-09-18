// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_id_mismatch_test — response-ID parity contract with the cocotb twin: a
// mismatching returned response ID is distinguishable through the master
// sequence API (observed == issued ^ mask, one-shot per direction, data
// path untouched, RLAST-beat burst sampling, clear_errors() disarm). The
// passive observation stack is disabled for this scenario: a
// corrupted response ID is an orphan completion to a passive observer.

class ocah_axi_id_mismatch_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_id_mismatch_test)

  function new(string name = "ocah_axi_id_mismatch_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(bit)::set(this, "m_env", "en_passive", 1'b0);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-BASE-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-WR-CAP");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-WR-DIFF");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-WR-DATA");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-WR-ONESHOT");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-BASE-RD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-RD-CAP");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-RD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-RD-DIFF");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-RD-DATA");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-RD-ONESHOT");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-BURST-RD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-BURST-RDATA");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-DISARM-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-IDC-DISARM-RD");
  endfunction

  task run_phase(uvm_phase phase);
    ocah_axi_id_mismatch_test_seq seq;
    phase.raise_objection(this, "ocah_axi_id_mismatch_test running");
    seq = ocah_axi_id_mismatch_test_seq::type_id::create("seq");
    seq.evidence  = m_env.m_checker;
    seq.slave_seq = m_env.m_slave_agent.seq;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_id_mismatch_test done");
  endtask

endclass : ocah_axi_id_mismatch_test
