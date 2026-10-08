// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test — the
// `read_security_gating_no_axi_activity` SMC fabric JTAG2AXI scenario.
// Security gating is a deterministic must-NOT-happen property checked per
// lifecycle bit with baseline/restore positive controls; this VPLAN scenario
// scopes the evidence to the no-activity window (gated attempts show zero
// request activity on the pulse counters, held across re-enable, with an
// exact activity delta through the restore read). Randomized read traffic
// on the same port lives in dtp_jtag2axi_smc_axi_read_random_ops_test.

class dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test)

  function new(string name = "dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("smc_axi",
                        '{
                            "CHK-AXI-NOACT",
                            "CHK-AXI-GATE-EXACT",
                            "CHK-AXI-RESP",
                            "CHK-AXI-RADDR",
                            "CHK-AXI-RDATA",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            DtpJ2aGateTdrCheckId
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_smc_axi_rd_test_seq seq = dtp_jtag2axi_smc_axi_rd_test_seq::type_id::create("seq");
    seq.scenario = "read_security_gating_no_axi_activity";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SMC_AXI_READ_SECURITY_GATING_NO_AXI_ACTIVITY_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test
