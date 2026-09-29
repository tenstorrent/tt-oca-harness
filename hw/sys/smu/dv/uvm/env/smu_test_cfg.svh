// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU test configuration: the highest configuration level and the only
// object the seed touches. Randomizes the four clock periods, the TCK
// period, and the post-reset settle from the runner seed over the same
// choice sets as the cocotb SmuEnvCfg.randomize_timing, carries the
// bring-up bounds of the cocotb base test and the scenario bounds of the
// cocotb sequences, the negative-validation switches, the scoreboard
// features a test requires, and the aggregate JTAG evidence policy. The
// base test fills the knobs (read_knobs), seeds and randomizes it once,
// then derives smu_env_cfg from it. The cocotb twin is
// cocotb_wrapper/env/smu_env_cfg.py.

class smu_test_cfg extends ocah_test_cfg;
  `uvm_object_utils(smu_test_cfg)

  // --- randomized timing (cocotb randomize_timing choice sets) ------------
  rand int unsigned ref_clk_period_ns;
  rand int unsigned smu_clk_period_ns;
  rand int unsigned periph_clk_period_ns;
  rand int unsigned sep_wdt_clk_period_ns;
  rand int unsigned tck_period_ns;
  rand int unsigned post_reset_settle_cycles;
  constraint smu_c {smu_clk_period_ns inside {8, 10, 12};}
  // clk_ref_i carries telemetry; a period equal to clk_smu_i leaves the two
  // domains indistinguishable at the boundary.
  constraint ref_c {
    ref_clk_period_ns inside {10, 12, 16};
    ref_clk_period_ns != smu_clk_period_ns;
  }
  constraint periph_c {periph_clk_period_ns inside {16, 20, 24};}
  constraint wdt_c {sep_wdt_clk_period_ns inside {80, 100, 120};}
  constraint tck_c {tck_period_ns inside {32, 40, 48};}
  // Above the cold-reset extender (255 ref cycles) plus deglitch margin.
  constraint settle_c {post_reset_settle_cycles inside {[500 : 700]};}
  // An SMC JTAG2AXI SERIES write returns zeros or parks in BUSY whenever
  // tck/smu is under 4 (cocotb smu_base_test.min_jtag_smu_ratio); a scenario
  // that issues one raises this floor in configure_test_cfg().
  int unsigned min_tck_smu_ratio = 0;
  constraint tck_ratio_c {tck_period_ns >= min_tck_smu_ratio * smu_clk_period_ns;}

  // --- bring-up bounds (cocotb smu_base_test.bring_up parity) -------------
  // Ref-clock cycles from clock start to power-good, and from power-good to
  // cold-reset release (power-good sync plus the 32-cycle cold deglitch).
  int unsigned powergood_delay_cycles = 10;
  int unsigned cold_release_delay_cycles = 64;
  // Bound on each reset-release poll (ref or smu clocks).
  int unsigned reset_release_timeout_cycles = 2000;

  // --- scenario bounds (cocotb sequence parity) ---------------------------
  int unsigned bound_tck = 2000;
  int unsigned bound_ref = 2000;
  int unsigned por_recover_ref_cycles = 64;
  int unsigned trst_hold_tck_cycles = 8;
  // The SMC eFuse sense of the default image completes 2280-2330 clk_smu
  // after the primary reset release; the expiry is about twice that
  // (cocotb smu_fuse_gate_helpers.FUSE_SENSE_BOUND_CYCLES).
  int unsigned fuse_sense_bound_cycles = 5000;
  // Gate path once the stall clears: prim_sync3 + sticky flop + 16-stage
  // pipe, about 20 clk_smc; a generous expiry, not a latency claim.
  int unsigned fuse_gate_release_bound_cycles = 256;
  // A level that must not move is watched for this long; every measured
  // release is checked to fit inside it.
  int unsigned fuse_gate_hold_cycles = 64;
  // Ref-clock cycles a cold-reset pulse is held inside a scenario.
  int unsigned cold_pulse_ref_cycles = 64;
  // Bridge status polls before a stuck-BUSY bridge fails the timeout inventory.
  int unsigned j2a_max_status_polls = 128;

  // --- negative-validation switches (must FAIL the run when set) ---------
  bit ptap_idcode_negative;  // +SMU_PTAP_IDCODE_NEGATIVE
  bit ic_reset_tdr_negative;  // +SMU_IC_RESET_SCOREBOARD_NEGATIVE
  bit debug_control_tdr_negative;  // +SMU_DEBUG_CONTROL_SCOREBOARD_NEGATIVE
  bit boot_gate_negative;  // +SMU_BOOT_GATE_SCOREBOARD_NEGATIVE
  bit j2a_ref_model_negative;  // +SMU_J2A_SCOREBOARD_NEGATIVE

  // --- evidence policy of the env-owned aggregate JTAG recorder ----------
  smu_evidence_policy_t jtag_policy;

  function new(string name = "smu_test_cfg");
    super.new(name);
  endfunction

  function void read_knobs();
    ptap_idcode_negative       = ocah_knobs::is_set("SMU_PTAP_IDCODE_NEGATIVE");
    ic_reset_tdr_negative      = ocah_knobs::is_set("SMU_IC_RESET_SCOREBOARD_NEGATIVE");
    debug_control_tdr_negative = ocah_knobs::is_set("SMU_DEBUG_CONTROL_SCOREBOARD_NEGATIVE");
    boot_gate_negative         = ocah_knobs::is_set("SMU_BOOT_GATE_SCOREBOARD_NEGATIVE");
    j2a_ref_model_negative     = ocah_knobs::is_set("SMU_J2A_SCOREBOARD_NEGATIVE");
  endfunction

  // Arm the aggregate JTAG recorder: zero checks or a missing ID fails.
  function void require_jtag_ids(string ids[$]);
    jtag_policy.require_checks = 1'b1;
    foreach (ids[i]) jtag_policy.required_ids.push_back(ids[i]);
  endfunction

  virtual function string convert2string();
    return $sformatf(
        {
          "%s ref_clk_period_ns=%0d smu_clk_period_ns=%0d periph_clk_period_ns=%0d ",
          "sep_wdt_clk_period_ns=%0d tck_period_ns=%0d settle_cycles=%0d idcode_negative=%0d ",
          "ic_reset_negative=%0d debug_control_negative=%0d boot_gate_negative=%0d ",
          "j2a_negative=%0d"
        },
        super.convert2string(),
        ref_clk_period_ns,
        smu_clk_period_ns,
        periph_clk_period_ns,
        sep_wdt_clk_period_ns,
        tck_period_ns,
        post_reset_settle_cycles,
        ptap_idcode_negative,
        ic_reset_tdr_negative,
        debug_control_tdr_negative,
        boot_gate_negative,
        j2a_ref_model_negative
    );
  endfunction

endclass : smu_test_cfg
