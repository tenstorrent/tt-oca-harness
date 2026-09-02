// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_series_write_incr_narrow_test — the
// `series_write_incr_narrow` SMC fabric JTAG2AXI scenario: SERIES_CTRL
// programs a 32-bit incrementing write stream whose base sits at beat
// offset +4, SERIES_DATA_INCR beats land on the AXI lanes selected by
// that address, and the responder backdoor plus final SERIES_CTRL
// capture prove the memory image and post-stream address.

class dtp_jtag2axi_smc_axi_series_write_incr_narrow_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_series_write_incr_narrow_test)

  function new(string name = "dtp_jtag2axi_smc_axi_series_write_incr_narrow_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.m_smc_axi_cfg.require_checks = 1'b1;
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-COMPLETION");
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-NONVAC");
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    dtp_jtag2axi_smc_axi_wr_test_seq seq = dtp_jtag2axi_smc_axi_wr_test_seq::type_id::create("seq");
    seq.scenario = "series_write_incr_narrow";
    return seq;
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_INCR_NARROW_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
    dtp_jtag2axi_smc_axi_wr_test_seq wr;
    super.plumb_scenario_seq(seq);
    if (!$cast(wr, seq)) `uvm_fatal(get_type_name(), "scenario sequence type mismatch")
    wr.axi_cfg       = m_env.m_smc_axi_cfg;
    wr.axi_evidence  = m_env.m_smc_axi_env.m_checker;
    wr.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
    wr.slave_seq     = m_env.m_smc_axi_slave_agent.seq;
  endfunction

endclass : dtp_jtag2axi_smc_axi_series_write_incr_narrow_test
