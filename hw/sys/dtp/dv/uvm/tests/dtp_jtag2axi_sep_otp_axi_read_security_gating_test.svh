// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sep_otp_axi_read_security_gating_test — the `read_security_gating`
// SEP OTP AXI-Lite JTAG2AXI scenario: two assert/release passes of the
// sep_otp_jtag2axi lifecycle disable prove a gated read attempt generates zero
// request activity (pulse counters, held across re-enable to catch delayed
// replays, plus an exact-delta proof through the restore read), while
// baseline/restore reads prove the observation path is alive.

class dtp_jtag2axi_sep_otp_axi_read_security_gating_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sep_otp_axi_read_security_gating_test)

  function new(string name = "dtp_jtag2axi_sep_otp_axi_read_security_gating_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("sep_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NOACT",
                            "CHK-AXI-GATE-EXACT",
                            "CHK-AXI-NONVAC",
                            DtpJ2aGateTdrCheckId
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "sep_otp_read_security_gating_seq"
    );
    seq.target_name = "sep_otp";
    seq.scenario    = "read_security_gating";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SEP_OTP_AXI_READ_SECURITY_GATING_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_sep_otp_axi_read_security_gating_test
