// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_series_write_read_no_incr_test — the
// `series_write_read_no_incr` SMC fabric JTAG2AXI scenario: a fixed-address
// series where every read beat must return the last value written and
// SERIES_CTRL's address must not advance.

class dtp_jtag2axi_smc_axi_series_write_read_no_incr_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_series_write_read_no_incr_test)

  function new(string name = "dtp_jtag2axi_smc_axi_series_write_read_no_incr_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{"CHK-AXI-RESP", "CHK-AXI-RDATA", "CHK-AXI-COMPLETION", "CHK-AXI-NONVAC"});
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_smc_axi_rd_test_seq seq = dtp_jtag2axi_smc_axi_rd_test_seq::type_id::create("seq");
    seq.scenario = "series_write_read_no_incr";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_READ_NO_INCR_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_smc_axi_rd_test_seq rd_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(rd_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not the rd-side type")
    rd_seq.axi_cfg       = m_env.m_smc_axi_cfg;
    rd_seq.axi_evidence  = m_env.m_smc_axi_env.m_checker;
    rd_seq.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_smc_axi_series_write_read_no_incr_test
