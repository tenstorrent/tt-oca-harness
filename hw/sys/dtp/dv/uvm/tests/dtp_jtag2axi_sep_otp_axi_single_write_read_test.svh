// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sep_otp_axi_single_write_read_test — JTAG2AXI single-op
// write-plus-readback traffic on the SEP OTP AXI-Lite port through
// the shared ocah_axi_vip passive env and slave agent: the written
// word must read back exactly, with the observed bus transactions
// matching the stimulus intents.

class dtp_jtag2axi_sep_otp_axi_single_write_read_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sep_otp_axi_single_write_read_test)

  function new(string name = "dtp_jtag2axi_sep_otp_axi_single_write_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("sep_otp",
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
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "sep_otp_single_write_read_seq"
    );
    seq.target_name = "sep_otp";
    seq.scenario    = "single_write_read";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SEP_OTP_AXI_SINGLE_WRITE_READ_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_jtag2axi_otp_axi_test_seq t_seq;
    super.plumb_scenario_seq(seq);
    if (!$cast(t_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_jtag2axi_otp_axi_test_seq")
    t_seq.axi_cfg       = m_env.m_sep_otp_axi_cfg;
    t_seq.axi_evidence  = m_env.m_sep_otp_axi_env.m_checker;
    t_seq.axi_ref_model = m_env.m_sep_otp_axi_env.m_ref_model;
  endfunction

endclass : dtp_jtag2axi_sep_otp_axi_single_write_read_test
