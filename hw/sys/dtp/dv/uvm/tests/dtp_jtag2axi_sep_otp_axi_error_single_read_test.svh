// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sep_otp_axi_error_single_read_test — VPLAN 4.2: SLVERR and
// DECERR single-read injections on the SEP OTP AXI-Lite port. Both injected
// responses must be classified as EXPECTED (CHK-AXI-ERR-INJ), the errored
// read's SINGLE_OP capture must return the RDATA of the errored beat and
// not the preloaded word (CHK-J2A-ERR-RDATA), the recovery read must
// return the preloaded reference data with OKAY (CHK-AXI-RDATA), and
// completion must stay within the poll bound.

class dtp_jtag2axi_sep_otp_axi_error_single_read_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sep_otp_axi_error_single_read_test)

  function new(string name = "dtp_jtag2axi_sep_otp_axi_error_single_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("sep_otp",
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
        "sep_otp_error_single_read_seq"
    );
    seq.target_name = "sep_otp";
    seq.scenario    = "error_single_read";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SEP_OTP_AXI_ERROR_SINGLE_READ_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_error_test_seq t_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(t_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_error_test_seq")
    t_seq.axi_cfg       = m_env.m_sep_otp_axi_cfg;
    t_seq.axi_evidence  = m_env.m_sep_otp_axi_env.m_checker;
    t_seq.axi_ref_model = m_env.m_sep_otp_axi_env.m_ref_model;
    t_seq.axi_reads     = m_env.m_axi_read_history["sep_otp"];
  endfunction

endclass : dtp_jtag2axi_sep_otp_axi_error_single_read_test
