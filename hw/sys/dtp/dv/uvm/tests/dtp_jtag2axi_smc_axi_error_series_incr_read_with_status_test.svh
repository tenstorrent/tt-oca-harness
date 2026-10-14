// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_error_series_incr_read_with_status_test — 3-beat
// incrementing series read through the WITH_ERROR_STATUS TDR with the fault
// armed on the middle beat. Each beat's capture shift returns the per-beat
// status MSB alongside the data, the injected response must be classified as
// EXPECTED (CHK-AXI-ERR-INJ), and the recovery read returns the reference
// data with OKAY.

class dtp_jtag2axi_smc_axi_error_series_incr_read_with_status_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_error_series_incr_read_with_status_test)

  function new(string name = "dtp_jtag2axi_smc_axi_error_series_incr_read_with_status_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-FAULT-STATUS",
                            "CHK-J2A-STATUS-BIT"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "smc_axi_error_series_incr_read_with_status_seq"
    );
    seq.target_name = "smc_axi";
    seq.scenario    = "error_series_incr_read_with_status";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_ERROR_SERIES_INCR_READ_WITH_STATUS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_axi_error_series_incr_read_with_status_test
