// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_dmi_status_test: on every bridge DTMCS shows the sticky DMI
// status, each DMI operation and each cause of the busy status behaves as the
// bridge defines, and op 3 and dmireset clear it. Every bridge records its
// own evidence, so a bridge the pass skipped fails at finalization.

class dtp_jtag2axi_dmi_status_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_dmi_status_test)

  function new(string name = "dtp_jtag2axi_dmi_status_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    super.configure_test_cfg(cfg);
    foreach (names[i]) begin
      cfg.require_axi_ids(names[i],
                          '{
                              "CHK-AXI-RESP",
                              "CHK-AXI-STRB",
                              "CHK-AXI-WADDR",
                              "CHK-AXI-WDATA",
                              "CHK-AXI-WMEM",
                              "CHK-AXI-COMPLETION",
                              "CHK-AXI-NONVAC",
                              "CHK-J2A-BUS-REQ",
                              "CHK-J2A-FAULT-STATUS",
                              "CHK-J2A-DTM-CAPTURE"
                          });
    end
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return dtp_jtag2axi_dmi_status_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_DMI_STATUS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_dmi_status_test
