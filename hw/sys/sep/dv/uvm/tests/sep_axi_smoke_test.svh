// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// sep_axi_smoke_test (`--items sep_axi_smoke_test`): runs
// sep_axi_smoke_test_seq on the environment's virtual sequencer once per
// pass and requires the scoreboard's cpu_ctrl_csr feature, so a pass whose
// CSR reads never reached the predictor fails at finalization.

class sep_axi_smoke_test extends sep_base_test;
  `uvm_component_utils(sep_axi_smoke_test)

  function new(string name = "sep_axi_smoke_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(sep_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_feature(SepFeatureCpuCtrlCsr);
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    return sep_axi_smoke_test_seq::type_id::create("seq");
  endfunction

  virtual function string specific_loops_knob();
    return "SEP_AXI_SMOKE_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "SEP_SYSTEM_TEST_LOOPS";
  endfunction

endclass : sep_axi_smoke_test
