// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_otp_axi_series_write_read_incr_oversize_test — the
// `series_write_read_incr_oversize` SMC OTP AXI-Lite JTAG2AXI scenario: an
// incrementing series write and per-beat read-back with the size field set
// above the 32-bit bus width, so every beat is one full bus-width beat. The
// shared passive AXI env compares every observed transaction; the required
// evidence IDs make a silent no-op run fail at finalization.

class dtp_jtag2axi_smc_otp_axi_series_write_read_incr_oversize_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_otp_axi_series_write_read_incr_oversize_test)

  function new(string name = "dtp_jtag2axi_smc_otp_axi_series_write_read_incr_oversize_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-SERIES-ADDR"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_otp_axi_test_seq seq = dtp_jtag2axi_otp_axi_test_seq::type_id::create(
        "smc_otp_series_write_read_incr_oversize_seq"
    );
    seq.target_name = "smc_otp";
    seq.scenario    = "series_write_read_incr_oversize";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_OTP_AXI_SERIES_WRITE_READ_INCR_OVERSIZE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_otp_axi_series_write_read_incr_oversize_test
