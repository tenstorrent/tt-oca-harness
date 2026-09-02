// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_series_write_read_incr_narrow_test — the
// `series_write_read_incr_narrow` SMC fabric JTAG2AXI scenario: write a
// 32-bit incrementing series at beat offset +4, then read every beat
// back through SERIES_CTRL(READ) + SERIES_DATA_INCR. Capture-DR must
// return the logical payload from the AXI lanes selected by that
// address. The shared passive AXI env compares every observed
// transaction; the required evidence IDs make a silent no-op run fail
// at finalization.

class dtp_jtag2axi_smc_axi_series_write_read_incr_narrow_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_series_write_read_incr_narrow_test)

  function new(string name = "dtp_jtag2axi_smc_axi_series_write_read_incr_narrow_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.m_smc_axi_cfg.require_checks = 1'b1;
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-RDATA");
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-COMPLETION");
    m_env.m_smc_axi_cfg.required_ids.push_back("CHK-AXI-NONVAC");
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    dtp_jtag2axi_smc_axi_rd_test_seq seq = dtp_jtag2axi_smc_axi_rd_test_seq::type_id::create("seq");
    seq.scenario = "series_write_read_incr_narrow";
    return seq;
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_READ_INCR_NARROW_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
    dtp_jtag2axi_smc_axi_rd_test_seq rd_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(rd_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not the rd-side type")
    rd_seq.axi_cfg       = m_env.m_smc_axi_cfg;
    rd_seq.axi_evidence  = m_env.m_smc_axi_env.m_checker;
    rd_seq.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
    rd_seq.slave_seq     = m_env.m_smc_axi_slave_agent.seq;
  endfunction

endclass : dtp_jtag2axi_smc_axi_series_write_read_incr_narrow_test
