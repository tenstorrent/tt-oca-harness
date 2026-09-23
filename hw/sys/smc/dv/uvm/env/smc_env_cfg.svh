// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC environment configuration, derived from smc_test_cfg and read by
// smc_env: the chosen clock periods, the SEP_IN master watchdog, the
// scoreboard features that must compare, the negative-validation switch
// the scoreboard predictor honors, and the memory footprint of the SYS_OUT
// responder. The env fills the VIP configs from
// this object and publishes the clock periods on smc_tb_if. Never
// randomized. The cocotb twin is env/smc_env_cfg.py.

class smc_env_cfg extends ocah_env_cfg;
  `uvm_object_utils(smc_env_cfg)

  // clk_period_ns (base) is the smc clock; the other two domains follow.
  int unsigned ref_clk_period_ns    = 10;
  int unsigned periph_clk_period_ns = 10;
  // SEP_IN master handshake watchdog (smc-clock cycles per wait).
  int unsigned axi_timeout_cycles = 10_000;
  // Scoreboard negative hooks, one per feature predictor: corrupt the
  // predicted scratch readback / the predicted catalogued default.
  bit csr_scoreboard_negative;
  bit default_reg_scoreboard_negative;
  bit lock_scoreboard_negative;
  bit mutex_scoreboard_negative;
  bit spm_mem_scoreboard_negative;
  // Backing memory of the SYS_OUT responder, in bytes (addresses wrap).
  int unsigned sys_out_mem_bytes = 32'h8000_0000;

  function new(string name = "smc_env_cfg");
    super.new(name);
  endfunction

  static function smc_env_cfg from_test_cfg(smc_test_cfg t);
    smc_env_cfg c = smc_env_cfg::type_id::create("env_cfg");
    c.clk_period_ns           = t.smc_clk_period_ns;
    c.ref_clk_period_ns       = t.ref_clk_period_ns;
    c.periph_clk_period_ns    = t.periph_clk_period_ns;
    c.axi_timeout_cycles      = t.axi_timeout_cycles;
    c.csr_scoreboard_negative = t.csr_scoreboard_negative;
    c.default_reg_scoreboard_negative = t.default_reg_scoreboard_negative;
    c.lock_scoreboard_negative = t.lock_scoreboard_negative;
    c.mutex_scoreboard_negative = t.mutex_scoreboard_negative;
    c.spm_mem_scoreboard_negative = t.spm_mem_scoreboard_negative;
    c.required_features       = t.required_features;
    return c;
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s ref_clk_period_ns=%0d periph_clk_period_ns=%0d axi_timeout_cycles=%0d",
        super.convert2string(),
        ref_clk_period_ns,
        periph_clk_period_ns,
        axi_timeout_cycles
    );
  endfunction

endclass : smc_env_cfg
