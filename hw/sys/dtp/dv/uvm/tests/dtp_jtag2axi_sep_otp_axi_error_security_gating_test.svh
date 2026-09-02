// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sep_otp_axi_error_security_gating_test — VPLAN 4.9: two
// assert/release passes of the sep_otp_jtag2axi lifecycle disable with an
// error-path write attempted while gated. The gated attempt (injection
// deliberately NOT expected-armed) must produce zero request activity
// across the attempt and after release (CHK-AXI-GATE-*, delayed-replay
// catch); each release restores normal error-path operation (armed DECERR
// EXPECTED via CHK-AXI-ERR-INJ) plus an OKAY recovery write.

class dtp_jtag2axi_sep_otp_axi_error_security_gating_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sep_otp_axi_error_security_gating_test)

  function new(string name = "dtp_jtag2axi_sep_otp_axi_error_security_gating_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    m_env.m_sep_otp_axi_cfg.require_checks = 1'b1;
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-RESP");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-ERR-INJ");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AW");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-GATE-W");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-GATE-AR");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-STRB");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-WADDR");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-WDATA");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-WMEM");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-COMPLETION");
    m_env.m_sep_otp_axi_cfg.required_ids.push_back("CHK-AXI-NONVAC");
  endfunction

  virtual function dtp_jtag_base_test_seq create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "sep_otp_error_security_gating_seq"
    );
    seq.target_name = "sep_otp";
    seq.scenario    = "error_security_gating";
    return seq;
  endfunction

  virtual function string specific_loops_plusarg();
    return "DTP_JTAG2AXI_SEP_OTP_AXI_ERROR_SECURITY_GATING_TEST_LOOPS";
  endfunction

  virtual function string group_loops_plusarg();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
    dtp_jtag2axi_error_test_seq t_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(t_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_error_test_seq")
    t_seq.axi_cfg       = m_env.m_sep_otp_axi_cfg;
    t_seq.axi_evidence  = m_env.m_sep_otp_axi_env.m_checker;
    t_seq.axi_ref_model = m_env.m_sep_otp_axi_env.m_ref_model;
    t_seq.slave_seq     = m_env.m_sep_otp_slave_agent.seq;
  endfunction

endclass : dtp_jtag2axi_sep_otp_axi_error_security_gating_test
