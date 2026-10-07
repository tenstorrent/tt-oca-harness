// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_responder_ops_test — the responder operations a DUT bench
// programs, proven on the harness bus: the errored-beat word of
// inject_error(), the W-before-AW order of arm_w_before_aw(), and the
// BUSER/RUSER streams of randomize_resp_user(), with the passive env scoring
// every access. The master assumes aresetn stays high while an item is in
// flight, so the reset drop is the cocotb twin's alone.

class ocah_axi_responder_ops_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_responder_ops_test)

  function new(string name = "ocah_axi_responder_ops_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-ERR-RDATA");
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-W-FIRST");
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-USER");
    m_env.m_axi_cfg.require_checks = 1'b1;
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
    m_env.m_axi_cfg.required_ids.push_back("CHK-AXI-ERR-INJ");
  endfunction

  task run_phase(uvm_phase phase);
    ocah_axi_responder_ops_test_seq seq;
    phase.raise_objection(this, "ocah_axi_responder_ops_test running");
    seq = ocah_axi_responder_ops_test_seq::type_id::create("seq");
    seq.evidence  = m_env.m_checker;
    seq.slave_seq = m_env.m_slave_agent.seq;
    seq.axi_cfg   = m_env.m_axi_cfg;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_responder_ops_test done");
  endtask

endclass : ocah_axi_responder_ops_test
