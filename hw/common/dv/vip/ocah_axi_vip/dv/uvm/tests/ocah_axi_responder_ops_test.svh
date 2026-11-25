// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ocah_axi_responder_ops_test — the responder operations a DUT bench
// programs, proven on the harness bus: the errored-beat word of
// inject_error(), the W-before-AW orders of arm_w_before_aw() and
// set_w_before_aw(), the BUSER/RUSER streams of randomize_resp_user(), the
// seeded READY stalls of enable_random_backpressure(), the B and R delays of
// set_response_delay(), and the AxCACHE/AxUSER/WUSER the monitor records,
// with the passive env scoring every access. The master assumes aresetn
// stays high while an item is in flight, so the reset drop is the cocotb
// twin's alone.

class ocah_axi_responder_ops_test extends ocah_axi_vip_base_test;
  `uvm_component_utils(ocah_axi_responder_ops_test)

  uvm_tlm_analysis_fifo #(ocah_axi_uvm_pkg::ocah_axi_item) m_observed;

  function new(string name = "ocah_axi_responder_ops_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_observed = new("m_observed", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    m_env.m_axi_env.item_ap.connect(m_observed.analysis_export);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.require_checks = 1'b1;
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-ERR-RDATA");
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-W-FIRST");
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-USER");
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-STALL");
    m_env.m_checker.required_ids.push_back("CHK-AXI-SLAVE-RESP-DELAY");
    m_env.m_checker.required_ids.push_back("CHK-AXI-MON-ATTR");
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
    seq.observed  = m_observed;
    seq.start(m_env.m_master_env.m_sequencer);
    phase.drop_objection(this, "ocah_axi_responder_ops_test done");
  endtask

endclass : ocah_axi_responder_ops_test
