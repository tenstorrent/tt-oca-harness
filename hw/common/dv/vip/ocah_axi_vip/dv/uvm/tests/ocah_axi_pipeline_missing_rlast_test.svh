// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_pipeline_missing_rlast_test: an AXI4 read whose beats stop before
// RLAST times out holding the beat it received, the other op of its
// pipeline keeps its result, and the master recovers. The passive stack is
// off because a read whose beats stop before RLAST is an in-flight
// transaction to a passive observer at the end of the run; the scenario
// runs on the harness bus, which carries no protocol SVA in this shape (the
// struct-port bundle does and would report the RLAST position).

class ocah_axi_pipeline_missing_rlast_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_pipeline_missing_rlast_test)

  function new(string name = "ocah_axi_pipeline_missing_rlast_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(bit)::set(this, "m_env", "en_passive", 1'b0);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-RLAST-TIMEOUT");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-RLAST-KEEP");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-RLAST-STATS");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-RLAST-WIRE");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-RLAST-ERROR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-RLAST-RECOVER");
  endfunction

  task run_phase(uvm_phase phase);
    ocah_axi_pipeline_missing_rlast_test_seq seq;
    phase.raise_objection(this, "ocah_axi_pipeline_missing_rlast_test running");
    seq = ocah_axi_pipeline_missing_rlast_test_seq::type_id::create("seq");
    seq.evidence  = m_env.m_checker;
    seq.slave_seq = m_env.m_slave_agent.seq;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_pipeline_missing_rlast_test done");
  endtask

endclass : ocah_axi_pipeline_missing_rlast_test
