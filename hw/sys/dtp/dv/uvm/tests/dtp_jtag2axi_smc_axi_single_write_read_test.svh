// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_single_write_read_test: on the SMC fabric bridge a
// System Bus Access write, a write to the neighbouring beat, and a read-back
// of the first word complete with the written word. The shared passive AXI
// env compares every observed transaction with the stimulus intents; the
// required evidence IDs make a silent no-op run fail at finalization.

class dtp_jtag2axi_smc_axi_single_write_read_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_single_write_read_test)

  function new(string name = "dtp_jtag2axi_smc_axi_single_write_read_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
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
                            "CHK-J2A-FAULT-STATUS"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_single_write_read_test_seq seq;
    seq = dtp_jtag2axi_single_write_read_test_seq::type_id::create("seq");
    seq.target = "smc_axi";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_SINGLE_WRITE_READ_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_axi_single_write_read_test
