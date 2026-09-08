// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_random_ops_test — the `random_ops` SMC OTP AXI-Lite
// JTAG2AXI scenario: seeded random single writes across sizes, addresses,
// payloads, and strobes, every write intent-armed for the shared AXI
// scoreboard.

class dtp_jtag2axi_smc_otp_axi_random_ops_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_random_ops_test)

  function new(string name = "dtp_jtag2axi_smc_otp_axi_random_ops_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "smc_otp_random_ops_seq"
    );
    seq.target_name = "smc_otp";
    seq.scenario    = "random_ops";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_OTP_AXI_RANDOM_OPS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_otp_axi_test_seq t_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(t_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_otp_axi_test_seq")
    t_seq.axi_cfg       = m_env.m_smc_otp_axi_cfg;
    t_seq.axi_evidence  = m_env.m_smc_otp_axi_env.m_checker;
    t_seq.axi_ref_model = m_env.m_smc_otp_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_smc_otp_axi_random_ops_test
