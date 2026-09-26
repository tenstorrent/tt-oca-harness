// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_error_series_no_incr_read_test — 3-beat fixed-address
// series read with the fault armed on the first beat. The injected response
// must be classified as EXPECTED (CHK-AXI-ERR-INJ), good beats return the
// preloaded fixed-address reference through the passive model compare
// (CHK-AXI-RDATA), the fault beat's capture is the data the errored beat
// carried (CHK-J2A-ERR-RDATA), and the recovery read completes with OKAY.

class dtp_jtag2axi_smc_axi_error_series_no_incr_read_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_error_series_no_incr_read_test)

  function new(string name = "dtp_jtag2axi_smc_axi_error_series_no_incr_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-ERR-RDATA"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "smc_axi_error_series_no_incr_read_seq"
    );
    seq.target_name = "smc_axi";
    seq.scenario    = "error_series_no_incr_read";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_ERROR_SERIES_NO_INCR_READ_TEST_LOOPS";
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
    err_seq.axi_reads     = m_env.m_axi_read_history["smc_axi"];
  endfunction

endclass : dtp_jtag2axi_smc_axi_error_series_no_incr_read_test
