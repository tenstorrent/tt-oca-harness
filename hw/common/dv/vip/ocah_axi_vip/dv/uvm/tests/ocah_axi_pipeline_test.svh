// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_pipeline_test — pipeline_result parity contract with the cocotb
// ocah_axi_lite_pipeline_test: single-beat reads and writes in flight
// together, judged against a per-cycle recording of the master interface,
// with the passive env scoring the same wires.

class ocah_axi_pipeline_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_pipeline_test)

  function new(string name = "ocah_axi_pipeline_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-ORDER");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-LAUNCH");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-HOLD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-STALL");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-DATA");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-OVERLAP");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-TIMEOUT");
    m_env.m_checker.required_ids.push_back("CHK-AXI-PIPE-ATOMIC");
    m_env.m_axi_cfg.require_checks = 1'b1;
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
  endfunction

  task run_phase(uvm_phase phase);
    ocah_axi_pipeline_test_seq seq;
    phase.raise_objection(this, "ocah_axi_pipeline_test running");
    seq = ocah_axi_pipeline_test_seq::type_id::create("seq");
    seq.evidence  = m_env.m_checker;
    seq.slave_cfg = m_env.m_slave_cfg;
    seq.slave_seq = m_env.m_slave_agent.seq;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_pipeline_test done");
  endtask

endclass : ocah_axi_pipeline_test
