// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_read_random_ops_test — the `read_random_ops` SMC OTP
// AXI-Lite JTAG2AXI scenario: randomized single reads at the bus width
// (address/payload) of backdoor-preloaded responder memory, every returned
// value checked in the sequence and every observed read compared by the
// shared passive env.

class dtp_jtag2axi_smc_otp_axi_read_random_ops_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_read_random_ops_test)

  function new(string name = "dtp_jtag2axi_smc_otp_axi_read_random_ops_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "smc_otp_read_random_ops_seq"
    );
    seq.target_name = "smc_otp";
    seq.scenario    = "read_random_ops";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_OTP_AXI_READ_RANDOM_OPS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_otp_axi_read_random_ops_test
