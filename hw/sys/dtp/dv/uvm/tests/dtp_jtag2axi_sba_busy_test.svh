// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sba_busy_test: with a bus access held outstanding on each
// bridge, sbcs reads sbbusy 1 past the poll bound, sbaddress reads proceed,
// and every sbcs, sbaddress and sbdata access the Debug Module refuses takes
// the busy status, sets sbbusyerror and changes nothing; the access then
// completes with its data. Every bridge records its own evidence, so a
// bridge the pass skipped fails at finalization.

class dtp_jtag2axi_sba_busy_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sba_busy_test)

  function new(string name = "dtp_jtag2axi_sba_busy_test", uvm_component parent = null);
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
                              "CHK-J2A-DTM-CAPTURE",
                              "CHK-J2A-ONE-XFER",
                              "CHK-J2A-SBA-BUSY"
                          });
    end
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag2axi_sba_busy_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SBA_BUSY_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_sba_busy_test
