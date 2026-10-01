// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_single_write_read_test — the `single_write_read` SMC
// fabric JTAG2AXI scenario: one write, a write to the neighbouring beat, and a
// readback of the first word through SMC_AXI_SINGLE_OP. The shared passive
// AXI env compares every observed transaction with the stimulus intents; the
// required evidence IDs make a silent no-op run fail at finalization.

class dtp_jtag2axi_smc_axi_single_write_read_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_single_write_read_test)

  function new(string name = "dtp_jtag2axi_smc_axi_single_write_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_smc_axi_rd_test_seq seq = dtp_jtag2axi_smc_axi_rd_test_seq::type_id::create("seq");
    seq.scenario = "single_write_read";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_SINGLE_WRITE_READ_TEST_LOOPS";
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

endclass : dtp_jtag2axi_smc_axi_single_write_read_test
