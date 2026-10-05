// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Environment configuration base: derived from the test cfg, read by the
// env, never randomized. A bench's <dut>_env_cfg adds agent geometry, memory
// sizes, monitor and scoreboard enables, and the chosen timing; the env
// fills each VIP config from it and publishes the clock period on tb_if.
// The cocotb twin is ocah_lib.OcahEnvCfg.

class ocah_env_cfg extends uvm_object;
  `uvm_object_utils(ocah_env_cfg)

  // System clock period the harness clock generator reads through tb_if.
  int unsigned clk_period_ns = 10;
  // Scoreboard features that must compare (copied from the test cfg).
  string required_features[$];

  function new(string name = "ocah_env_cfg");
    super.new(name);
  endfunction

  virtual function string convert2string();
    return $sformatf("clk_period_ns=%0d required_features=%p", clk_period_ns, required_features);
  endfunction

endclass : ocah_env_cfg
