// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Test configuration base: the highest configuration level and the only
// object the seed touches. A bench's <dut>_test_cfg adds the rand fields
// worth randomizing (timing, sizes, modes), the knob-derived controls, the
// features the scoreboard must compare, and the scenario evidence policy;
// the base test fills `seed` and `random_count` from the knob accessor, then
// calls srandom(seed) and randomize() once. The env cfg is derived from
// this object (<dut>_env_cfg::from_test_cfg) and is what the env reads.
// The cocotb twin is ocah_lib.OcahTestCfg.

class ocah_test_cfg extends uvm_object;
  `uvm_object_utils(ocah_test_cfg)

  // Runner seed (the simulator seed plusarg, read once by ocah_test).
  int unsigned seed = 1;
  // Random patterns or operations per scenario pass.
  int unsigned random_count = 5;
  // Scoreboard features that must record at least one comparison and no
  // mismatch for the run to pass (<dut>_scoreboard feature names).
  string required_features[$];

  function new(string name = "ocah_test_cfg");
    super.new(name);
  endfunction

  function void require_feature(string feature);
    foreach (required_features[i]) if (required_features[i] == feature) return;
    required_features.push_back(feature);
  endfunction

  // One line for the build-time configuration echo.
  virtual function string convert2string();
    return $sformatf("seed=%0d random_count=%0d required_features=%p", seed, random_count,
                     required_features);
  endfunction

endclass : ocah_test_cfg
