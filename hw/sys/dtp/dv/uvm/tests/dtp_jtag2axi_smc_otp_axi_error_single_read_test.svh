// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_error_single_read_test — SLVERR and DECERR
// single-read injections on the SMC OTP AXI-Lite port. Both injected
// responses must be classified as EXPECTED (CHK-AXI-ERR-INJ), the errored
// read's SINGLE_OP capture must return the RDATA of the errored beat and not
// the preloaded word (CHK-J2A-ERR-RDATA), the recovery read must return the
// preloaded reference data with OKAY (CHK-AXI-RDATA), and completion must
// stay within the poll bound.

class dtp_jtag2axi_smc_otp_axi_error_single_read_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_error_single_read_test)

  function new(string name = "dtp_jtag2axi_smc_otp_axi_error_single_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-ERR-RDATA",
                            "CHK-J2A-FAULT-STATUS"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "smc_otp_error_single_read_seq"
    );
    seq.target_name = "smc_otp";
    seq.scenario    = "error_single_read";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_OTP_AXI_ERROR_SINGLE_READ_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_otp_axi_error_single_read_test
