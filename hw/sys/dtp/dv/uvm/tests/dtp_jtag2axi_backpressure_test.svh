// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_backpressure_test: every bridge completes its writes and reads
// under seeded READY stalls and response delays, with the transfer attributes
// the specification fixes and one transfer at a time on its port. Every
// bridge records its own evidence, so a bridge the pass skipped fails at
// finalization.

class dtp_jtag2axi_backpressure_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_backpressure_test)

  function new(string name = "dtp_jtag2axi_backpressure_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    super.configure_test_cfg(cfg);
    foreach (names[i]) begin
      cfg.require_axi_ids(names[i],
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
                              "CHK-J2A-BUS-REQ",
                              "CHK-J2A-AXI-ATTR",
                              "CHK-J2A-FAULT-STATUS",
                              "CHK-J2A-ONE-XFER"
                          });
    end
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag2axi_backpressure_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_BACKPRESSURE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_backpressure_test
