// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_write_security_gating_test — the
// `write_security_gating` SMC fabric JTAG2AXI scenario: two assert/release
// passes of the smc_jtag2axi lifecycle disable prove a gated write attempt
// generates no request activity (pulse counters), leaves the sentinel-
// preloaded memory untouched (including after release — the delayed-replay
// leak), and that exactly one sanctioned restore write completes per pass
// (responder burst counts). A fixed-address series write with beats queued
// behind one held on the bus then proves the disable drops the queued beats.

class dtp_jtag2axi_smc_axi_write_security_gating_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_write_security_gating_test)

  function new(string name = "dtp_jtag2axi_smc_axi_write_security_gating_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-GATE-AW",
                            "CHK-AXI-GATE-W",
                            "CHK-AXI-GATE-AR",
                            "CHK-AXI-GATE-EXACT",
                            "CHK-AXI-NONVAC",
                            DtpJ2aGateTdrCheckId
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_smc_axi_wr_test_seq seq = dtp_jtag2axi_smc_axi_wr_test_seq::type_id::create("seq");
    seq.scenario = "write_security_gating";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_WRITE_SECURITY_GATING_TEST_LOOPS";
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

endclass : dtp_jtag2axi_smc_axi_write_security_gating_test
