// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC test configuration: the highest configuration level and the only
// object the seed touches. Randomizes the three clock periods from the
// runner seed over the same choice sets as the cocotb
// SmcEnvCfg.randomize_timing (ref/periph 8, 10, 12 ns; smc 4, 5, 6 ns),
// carries the bring-up and bounded-wait constants of the cocotb env cfg,
// the negative-validation switch, and the scoreboard features a test
// requires. The base test fills the knobs (read_knobs), seeds and
// randomizes it once, then derives smc_env_cfg from it. The cocotb twin is
// env/smc_env_cfg.py.

class smc_test_cfg extends ocah_test_cfg;
  `uvm_object_utils(smc_test_cfg)

  // --- randomized timing --------------------------------------------------
  rand int unsigned ref_clk_period_ns;
  rand int unsigned smc_clk_period_ns;
  rand int unsigned periph_clk_period_ns;
  constraint ref_c {ref_clk_period_ns inside {8, 10, 12};}
  constraint smc_c {smc_clk_period_ns inside {4, 5, 6};}
  constraint periph_c {periph_clk_period_ns inside {8, 10, 12};}

  // --- bring-up and bounded waits (cocotb SmcEnvCfg parity) ----------------
  // Ref-clock cycles after cold-reset release before the first pass.
  int unsigned post_reset_settle_cycles = 500;
  // smc-clock bound on the fuse-sense / warm-domain release wait
  // (cocotb smc_base_test_seq.wait_fuse_sense_done max_cycles).
  int unsigned fuse_sense_timeout_cycles = 200_000;
  // SEP_IN master handshake watchdog, in smc-clock cycles per wait: the
  // cocotb 50 us AXI timeout at the 5 ns nominal smc clock.
  int unsigned axi_timeout_cycles = 10_000;

  // --- negative-validation switches (must FAIL the run when set) ---------
  bit csr_scoreboard_negative;   // +SMC_CSR_SCOREBOARD_NEGATIVE
  bit default_reg_scoreboard_negative;  // +SMC_DEFAULT_REG_SCOREBOARD_NEGATIVE
  bit lock_scoreboard_negative;  // +SMC_LOCK_SCOREBOARD_NEGATIVE
  bit mutex_scoreboard_negative;  // +SMC_MUTEX_SCOREBOARD_NEGATIVE
  bit spm_mem_scoreboard_negative;  // +SMC_SPM_MEM_SCOREBOARD_NEGATIVE

  function new(string name = "smc_test_cfg");
    super.new(name);
  endfunction

  // Fill the knob-derived controls through the one knob accessor.
  function void read_knobs();
    csr_scoreboard_negative = ocah_knobs::is_set("SMC_CSR_SCOREBOARD_NEGATIVE");
    default_reg_scoreboard_negative =
            ocah_knobs::is_set("SMC_DEFAULT_REG_SCOREBOARD_NEGATIVE");
    lock_scoreboard_negative = ocah_knobs::is_set("SMC_LOCK_SCOREBOARD_NEGATIVE");
    mutex_scoreboard_negative = ocah_knobs::is_set("SMC_MUTEX_SCOREBOARD_NEGATIVE");
    spm_mem_scoreboard_negative =
            ocah_knobs::is_set("SMC_SPM_MEM_SCOREBOARD_NEGATIVE");
  endfunction

  // Replace the required scoreboard features.
  function void set_required_features(string features[$]);
    required_features.delete();
    foreach (features[i]) require_feature(features[i]);
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s ref_clk_period_ns=%0d smc_clk_period_ns=%0d periph_clk_period_ns=%0d csr_negative=%0d",
        super.convert2string(),
        ref_clk_period_ns,
        smc_clk_period_ns,
        periph_clk_period_ns,
        csr_scoreboard_negative
    );
  endfunction

endclass : smc_test_cfg
