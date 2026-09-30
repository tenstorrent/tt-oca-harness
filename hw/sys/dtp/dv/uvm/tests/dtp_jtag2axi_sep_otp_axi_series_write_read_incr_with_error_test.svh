// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sep_otp_axi_series_write_read_incr_with_error_test — the
// `series_write_read_incr_with_error` SEP OTP AXI-Lite JTAG2AXI scenario:
// *_SERIES_DATA_WITH_ERROR_STATUS mode with a mixed increment pattern on
// both legs: a clean write leg, then a read leg from one SERIES_CTRL
// preload with one armed SLVERR/DECERR beat whose lagged status bit is
// judged on every shift (CHK-J2A-STATUS-BIT), each leg ending with the
// SERIES_CTRL address capture and a legal single read proving recovery.

class dtp_jtag2axi_sep_otp_axi_series_write_read_incr_with_error_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sep_otp_axi_series_write_read_incr_with_error_test)

  function new(string name = "dtp_jtag2axi_sep_otp_axi_series_write_read_incr_with_error_test",
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
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-STATUS-BIT"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "sep_otp_series_write_read_incr_with_error_seq"
    );
    seq.target_name = "sep_otp";
    seq.scenario    = "series_write_read_incr_with_error";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SEP_OTP_AXI_SERIES_WRITE_READ_INCR_WITH_ERROR_TEST_LOOPS";
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

endclass : dtp_jtag2axi_sep_otp_axi_series_write_read_incr_with_error_test
