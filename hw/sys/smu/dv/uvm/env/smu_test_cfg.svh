// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU test configuration: the highest configuration level and the only
// object the seed touches. Randomizes the three clock periods, the TCK
// period, and the post-reset settle from the runner seed over the same
// choice sets as the cocotb SmuEnvCfg.randomize_timing, carries the
// bring-up bounds of the cocotb base test and the scenario bounds of the
// cocotb smoke sequence, the negative-validation switch, the scoreboard
// features a test requires, and the aggregate JTAG evidence policy. The
// base test fills the knobs (read_knobs), seeds and randomizes it once,
// then derives smu_env_cfg from it. The cocotb twin is env/smu_env_cfg.py.

class smu_test_cfg extends ocah_test_cfg;
  `uvm_object_utils(smu_test_cfg)

  // --- randomized timing (cocotb randomize_timing choice sets) ------------
  rand int unsigned ref_clk_period_ns;
  rand int unsigned smu_clk_period_ns;
  rand int unsigned periph_clk_period_ns;
  rand int unsigned tck_period_ns;
  rand int unsigned post_reset_settle_cycles;
  constraint ref_c {ref_clk_period_ns inside {8, 10, 12, 16};}
  constraint smu_c {smu_clk_period_ns inside {8, 10, 12};}
  constraint periph_c {periph_clk_period_ns inside {8, 10, 12, 16};}
  constraint tck_c {tck_period_ns inside {32, 40, 48};}
  // Above the cold-reset extender (255 ref cycles) plus deglitch margin.
  constraint settle_c {post_reset_settle_cycles inside {[500 : 700]};}

  // --- bring-up bounds (cocotb smu_base_test.bring_up parity) -------------
  // Ref-clock cycles from clock start to power-good, and from power-good to
  // cold-reset release (power-good sync plus the 32-cycle cold deglitch).
  int unsigned powergood_delay_cycles = 10;
  int unsigned cold_release_delay_cycles = 64;
  // Bound on each reset-release poll (ref or smu clocks).
  int unsigned reset_release_timeout_cycles = 2000;

  // --- scenario bounds (cocotb smu_dtp_jtag_smoke_test_seq parity) -------
  int unsigned bound_tck = 2000;
  int unsigned bound_ref = 2000;
  int unsigned por_recover_ref_cycles = 64;
  int unsigned trst_hold_tck_cycles = 8;

  // --- negative-validation switch (must FAIL the run when set) -----------
  bit ptap_idcode_negative;  // +SMU_PTAP_IDCODE_NEGATIVE

  // --- evidence policy of the env-owned aggregate JTAG recorder ----------
  smu_evidence_policy_t jtag_policy;

  function new(string name = "smu_test_cfg");
    super.new(name);
  endfunction

  function void read_knobs();
    ptap_idcode_negative = ocah_knobs::is_set("SMU_PTAP_IDCODE_NEGATIVE");
  endfunction

  // Arm the aggregate JTAG recorder: zero checks or a missing ID fails.
  function void require_jtag_ids(string ids[$]);
    jtag_policy.require_checks = 1'b1;
    foreach (ids[i]) jtag_policy.required_ids.push_back(ids[i]);
  endfunction

  function void set_required_features(string features[$]);
    required_features.delete();
    foreach (features[i]) require_feature(features[i]);
  endfunction

  virtual function string convert2string();
    return $sformatf(
        {
          "%s ref_clk_period_ns=%0d smu_clk_period_ns=%0d periph_clk_period_ns=%0d ",
          "tck_period_ns=%0d settle_cycles=%0d idcode_negative=%0d"
        },
        super.convert2string(),
        ref_clk_period_ns,
        smu_clk_period_ns,
        periph_clk_period_ns,
        tck_period_ns,
        post_reset_settle_cycles,
        ptap_idcode_negative
    );
  endfunction

endclass : smu_test_cfg
