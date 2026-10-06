// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC test configuration: the highest configuration level and the only
// object the seed touches. Carries the periods of the three pll_wrap clocks
// (ref and periph fixed, sys from +pll_sys_period_ns, as the cocotb
// SmcEnvCfg resolves them), the bring-up and bounded-wait constants of the
// cocotb env cfg, the negative-validation switch, and the scoreboard
// features a test requires. The base test fills the knobs (read_knobs),
// seeds and randomizes it once, then derives smc_env_cfg from it. The cocotb
// twin is env/smc_env_cfg.py.

class smc_test_cfg extends ocah_test_cfg;
  `uvm_object_utils(smc_test_cfg)

  // --- pll_wrap clock periods ---------------------------------------------
  // ref and periph are fixed by the model; sys follows +pll_sys_period_ns
  // (1.25 ns default, 10 ns the alternative), read in read_knobs.
  real ref_clk_period_ns    = 10.0;
  real smc_clk_period_ns    = 1.25;
  real periph_clk_period_ns = 5.0;

  // --- bring-up and bounded waits (cocotb SmcEnvCfg parity) ----------------
  // Ref-clock cycles after cold-reset release before the first pass.
  int unsigned post_reset_settle_cycles = 500;
  // smc-clock bound on the fuse-sense / warm-domain release wait
  // (cocotb smc_base_test_seq.wait_fuse_sense_done max_cycles).
  int unsigned fuse_sense_timeout_cycles = 200_000;
  // SEP_IN master handshake watchdog, in smc-clock cycles per wait: the
  // cocotb 50 us AXI timeout at the 1.25 ns default smc clock.
  int unsigned axi_timeout_cycles = 40_000;

  // --- negative-validation switches (must FAIL the run when set) ---------
  bit csr_scoreboard_negative;   // +SMC_CSR_SCOREBOARD_NEGATIVE
  bit default_reg_scoreboard_negative;  // +SMC_DEFAULT_REG_SCOREBOARD_NEGATIVE
  bit lock_scoreboard_negative;  // +SMC_LOCK_SCOREBOARD_NEGATIVE
  bit mutex_scoreboard_negative;  // +SMC_MUTEX_SCOREBOARD_NEGATIVE
  bit spm_mem_scoreboard_negative;  // +SMC_SPM_MEM_SCOREBOARD_NEGATIVE
  bit regblock_wide_scoreboard_negative;  // +SMC_REGBLOCK_WIDE_SCOREBOARD_NEGATIVE
  bit regblock_wide_sequence_negative;  // +SMC_REGBLOCK_WIDE_SEQUENCE_NEGATIVE

  function new(string name = "smc_test_cfg");
    super.new(name);
  endfunction

  // Fill the knob-derived controls through the one knob accessor, and the
  // sys period from the plusarg pll_wrap itself reads.
  function void read_knobs();
    void'($value$plusargs("pll_sys_period_ns=%f", smc_clk_period_ns));
    csr_scoreboard_negative = ocah_knobs::is_set("SMC_CSR_SCOREBOARD_NEGATIVE");
    default_reg_scoreboard_negative =
            ocah_knobs::is_set("SMC_DEFAULT_REG_SCOREBOARD_NEGATIVE");
    lock_scoreboard_negative = ocah_knobs::is_set("SMC_LOCK_SCOREBOARD_NEGATIVE");
    mutex_scoreboard_negative = ocah_knobs::is_set("SMC_MUTEX_SCOREBOARD_NEGATIVE");
    spm_mem_scoreboard_negative =
            ocah_knobs::is_set("SMC_SPM_MEM_SCOREBOARD_NEGATIVE");
    regblock_wide_scoreboard_negative =
            ocah_knobs::is_set("SMC_REGBLOCK_WIDE_SCOREBOARD_NEGATIVE");
    regblock_wide_sequence_negative =
            ocah_knobs::is_set("SMC_REGBLOCK_WIDE_SEQUENCE_NEGATIVE");
  endfunction

  // Replace the required scoreboard features.
  function void set_required_features(string features[$]);
    required_features.delete();
    foreach (features[i]) require_feature(features[i]);
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s ref_clk_period_ns=%0g smc_clk_period_ns=%0g periph_clk_period_ns=%0g csr_negative=%0d",
        super.convert2string(),
        ref_clk_period_ns,
        smc_clk_period_ns,
        periph_clk_period_ns,
        csr_scoreboard_negative
    );
  endfunction

endclass : smc_test_cfg
