// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_error_series_no_incr_write_test — 3-beat fixed-address
// series write with the fault on the middle beat, armed after the first beat is
// published. The injected response must be classified as EXPECTED
// (CHK-AXI-ERR-INJ), good beats commit to the fixed address, and the recovery
// write proves no stuck state (CHK-AXI-WMEM against the stimulus intent).

class dtp_jtag2axi_smc_axi_error_series_no_incr_write_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_error_series_no_incr_write_test)

  function new(string name = "dtp_jtag2axi_smc_axi_error_series_no_incr_write_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-FAULT-STATUS",
                            "CHK-J2A-SERIES-ADDR"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "smc_axi_error_series_no_incr_write_seq"
    );
    seq.target_name = "smc_axi";
    seq.scenario    = "error_series_no_incr_write";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_ERROR_SERIES_NO_INCR_WRITE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_axi_error_series_no_incr_write_test
