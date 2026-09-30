// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_error_single_write_test — SLVERR and DECERR
// single-write injections on the SMC fabric port. Both injected responses
// must be classified as EXPECTED (CHK-AXI-ERR-INJ), every front-door write's
// strobes must match the stimulus wstrb, the failed write commits nothing,
// recovery-write memory must equal the stimulus intent (CHK-AXI-WMEM), and
// completion must stay within the poll bound.

class dtp_jtag2axi_smc_axi_error_single_write_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_error_single_write_test)

  function new(string name = "dtp_jtag2axi_smc_axi_error_single_write_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-FAULT-STATUS"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "smc_axi_error_single_write_seq"
    );
    seq.target_name = "smc_axi";
    seq.scenario    = "error_single_write";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_ERROR_SINGLE_WRITE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_error_test_seq err_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(err_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_error_test_seq")
    err_seq.axi_cfg       = m_env.m_smc_axi_cfg;
    err_seq.axi_evidence  = m_env.m_smc_axi_env.m_checker;
    err_seq.axi_ref_model = m_env.m_smc_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_smc_axi_error_single_write_test
