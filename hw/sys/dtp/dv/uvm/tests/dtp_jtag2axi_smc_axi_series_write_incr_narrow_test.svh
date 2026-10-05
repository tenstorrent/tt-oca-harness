// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_series_write_incr_narrow_test — the
// `series_write_incr_narrow` SMC fabric JTAG2AXI scenario: SERIES_CTRL
// programs a 32-bit incrementing write stream whose base sits at beat
// offset +4, SERIES_DATA_INCR beats land on the AXI lanes selected by
// that address (per-beat strobe and lane-data intents: CHK-AXI-STRB,
// CHK-AXI-WDATA, CHK-AXI-WADDR), a sentinel beside the stream stays
// untouched, and the responder backdoor plus final SERIES_CTRL capture
// prove the memory image and post-stream address.

class dtp_jtag2axi_smc_axi_series_write_incr_narrow_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_series_write_incr_narrow_test)

  function new(string name = "dtp_jtag2axi_smc_axi_series_write_incr_narrow_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-SERIES-ADDR"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_smc_axi_wr_test_seq seq = dtp_jtag2axi_smc_axi_wr_test_seq::type_id::create("seq");
    seq.scenario = "series_write_incr_narrow";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_INCR_NARROW_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_smc_axi_wr_test_seq wr;
    super.plumb_scenario_seq(seq);
    if (!$cast(wr, seq)) `uvm_fatal(get_type_name(), "scenario sequence type mismatch")
    wr.axi_cfg       = m_env.m_smc_axi_cfg;
    wr.axi_evidence  = m_env.m_smc_axi_env.m_checker;
    wr.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_smc_axi_series_write_incr_narrow_test
