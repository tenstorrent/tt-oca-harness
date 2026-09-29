// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_smc_dtp_jtag2axi_smoke_test (`--items smu_smc_dtp_jtag2axi_smoke_test`):
// runs smu_smc_dtp_jtag2axi_smoke_test_seq on the environment's virtual
// sequencer once per pass and requires the scoreboard features the scenario
// exercises (ir_decode, jtag2axi_req, jtag2axi_status) and the aggregate TAP
// evidence, so a pass whose accesses never reached the reference models fails
// at finalization.

class smu_smc_dtp_jtag2axi_smoke_test extends smu_base_test;
  `uvm_component_utils(smu_smc_dtp_jtag2axi_smoke_test)

  function new(string name = "smu_smc_dtp_jtag2axi_smoke_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(smu_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(dtp_env_pkg::DtpFeatureIrDecode);
    cfg.require_feature(dtp_env_pkg::DtpFeatureJtag2axiReq);
    cfg.require_feature(dtp_env_pkg::DtpFeatureJtag2axiStatus);
    cfg.require_jtag_ids('{"CHK-TAP-STATE", "CHK-TAP-RESET-TLR"});
    // An SMC JTAG2AXI SERIES write parks in BUSY under a tck/smu ratio below 4.
    cfg.min_tck_smu_ratio = 4;
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return smu_smc_dtp_jtag2axi_smoke_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SMU_SMC_DTP_JTAG2AXI_SMOKE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SMU_DTP_TEST_LOOPS";
  endfunction

endclass : smu_smc_dtp_jtag2axi_smoke_test
