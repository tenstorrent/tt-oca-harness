// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_error_security_gating_test — two assert/release
// passes of the smc_otp_jtag2axi lifecycle disable with an error-path write
// attempted while gated. The gated attempt (injection NOT expected-armed) must
// produce zero request activity across the attempt and after release
// (CHK-AXI-GATE-*, delayed-replay catch); each release restores normal
// error-path operation (an armed SLVERR and DECERR, one per pass in seeded
// order, EXPECTED via CHK-AXI-ERR-INJ) plus an OKAY recovery write.

class dtp_jtag2axi_smc_otp_axi_error_security_gating_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_error_security_gating_test)

  function new(string name = "dtp_jtag2axi_smc_otp_axi_error_security_gating_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-GATE-AW",
                            "CHK-AXI-GATE-W",
                            "CHK-AXI-GATE-AR",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-FAULT-STATUS",
                            "CHK-AXI-GATE-EXACT",
                            DtpJ2aGateTdrCheckId
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "smc_otp_error_security_gating_seq"
    );
    seq.target_name = "smc_otp";
    seq.scenario    = "error_security_gating";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_OTP_AXI_ERROR_SECURITY_GATING_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_error_test_seq t_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(t_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_error_test_seq")
    t_seq.axi_cfg       = m_env.m_smc_otp_axi_cfg;
    t_seq.axi_evidence  = m_env.m_smc_otp_axi_env.m_checker;
    t_seq.axi_ref_model = m_env.m_smc_otp_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_smc_otp_axi_error_security_gating_test
