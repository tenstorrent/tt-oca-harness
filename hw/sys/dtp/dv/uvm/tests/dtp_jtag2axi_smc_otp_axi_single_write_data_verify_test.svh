// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_single_write_data_verify_test — the
// `single_write_data_verify` SMC OTP AXI-Lite JTAG2AXI scenario: write a seeded
// non-trivial payload, then read it back through the bridge; both legs are
// intent-armed so the scoreboard proves the bus-side write and readback.

class dtp_jtag2axi_smc_otp_axi_single_write_data_verify_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_single_write_data_verify_test)

  function new(string name = "dtp_jtag2axi_smc_otp_axi_single_write_data_verify_test",
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
                            "CHK-AXI-RADDR",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "smc_otp_single_write_data_verify_seq"
    );
    seq.target_name = "smc_otp";
    seq.scenario    = "single_write_data_verify";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_OTP_AXI_SINGLE_WRITE_DATA_VERIFY_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_otp_axi_single_write_data_verify_test
