// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_series_write_incr_test — the `series_write_incr`
// SMC fabric JTAG2AXI scenario: SERIES_CTRL programs an incrementing write
// stream, SERIES_DATA_INCR beats land at strided addresses (verified via
// the responder backdoor), and the final SERIES_CTRL capture proves the
// settled status and post-stream address.

class dtp_jtag2axi_smc_axi_series_write_incr_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_series_write_incr_test)

  function new(string name = "dtp_jtag2axi_smc_axi_series_write_incr_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_smc_axi_wr_test_seq seq = dtp_jtag2axi_smc_axi_wr_test_seq::type_id::create("seq");
    seq.scenario = "series_write_incr";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_INCR_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_axi_series_write_incr_test
