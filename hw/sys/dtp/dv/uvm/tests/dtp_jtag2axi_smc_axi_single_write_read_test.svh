// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_single_write_read_test — the single write/read scenario
// on the SMC fabric AXI4 manager port (132-bit wide TDR scans, 64-bit data,
// ID-tagged bursts observed by the shared monitor).

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
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-GATE-AW",
                            "CHK-AXI-GATE-AR"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_single_write_read_test_seq seq =
            dtp_jtag2axi_single_write_read_test_seq::type_id::create(
        "seq"
    );
    seq.target_name = "smc_axi";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_SINGLE_WRITE_READ_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_single_write_read_test_seq wr_rd;
    super.plumb_scenario_seq(seq);
    if (!$cast(wr_rd, seq))
      `uvm_fatal(get_type_name(),
                 "scenario sequence is not a dtp_jtag2axi_single_write_read_test_seq")
    wr_rd.axi_cfg       = m_env.m_smc_axi_cfg;
    wr_rd.axi_evidence  = m_env.m_smc_axi_env.m_checker;
    wr_rd.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_smc_axi_single_write_read_test
