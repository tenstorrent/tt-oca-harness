// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_struct_bridge_test — the shared slave agent behind
// ocah_axi_struct_bridge, proven full-stack from the struct side: backdoor
// preload, random single beats of every size, INCR/FIXED/WRAP bursts, partial
// strobes, one-shot faults, response holds, and READY stalls, with the passive
// env scoring the interface side. Required
// CHK-* evidence on both the scenario checker and the wire-level scoreboard.

class ocah_axi_struct_bridge_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_struct_bridge_test)

  function new(string name = "ocah_axi_struct_bridge_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-PRELOAD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-RDBACK");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-BACKDOOR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-ID");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-BURST");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-WRAP");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-STRB");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-FAULT-RD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-FAULT-WR");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-HOLD");
    m_env.m_checker.required_ids.push_back("CHK-AXI-BRIDGE-BACKPRESSURE");
    m_env.m_mt_axi_cfg.require_checks = 1'b1;
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-RADDR");
    m_env.m_mt_axi_cfg.required_ids.push_back("CHK-AXI-ERR-INJ");
  endfunction

  task run_phase(uvm_phase phase);
    ocah_axi_struct_bridge_test_seq seq;
    phase.raise_objection(this, "ocah_axi_struct_bridge_test running");
    seq = ocah_axi_struct_bridge_test_seq::type_id::create("seq");
    seq.evidence  = m_env.m_checker;
    seq.axi_cfg   = m_env.m_mt_axi_cfg;
    seq.slave_seq = m_env.m_mt_slave_agent.seq;
    seq.shadow    = m_env.m_mt_axi_env.m_ref_model;
    seq.start(m_env.m_mt_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_struct_bridge_test done");
  endtask

endclass : ocah_axi_struct_bridge_test
