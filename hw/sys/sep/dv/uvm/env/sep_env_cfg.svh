// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP environment configuration, derived from sep_test_cfg and read by
// sep_env: the chosen clock periods, the CPU-LSU master watchdog, the
// scoreboard features that must compare, and the negative-validation switch
// the scoreboard predictor honors. The env fills the VIP configs from this
// object and publishes the clock periods on sep_tb_if. Never randomized.
// The cocotb twin is cocotb/env/sep_env_cfg.py.

class sep_env_cfg extends ocah_env_cfg;
  `uvm_object_utils(sep_env_cfg)

  // clk_i at 800 MHz and clk_ref_i at 100 MHz. The base clk_period_ns is
  // an integer and cannot hold 1.25, so the harness reads these fields.
  real sys_clk_period_ns = 1.25;
  real ref_clk_period_ns = 10.0;
  int unsigned wdt_clk_period_ns     = 5000;
  int unsigned entropy_clk_period_ns = 3;
  // CPU-LSU master handshake watchdog (system-clock cycles per wait).
  // 40_000 cycles at 1.25 ns is the cocotb 50 us AXI timeout.
  int unsigned axi_timeout_cycles = 40_000;
  // Scoreboard negative hook: corrupt the predicted CSR readback.
  bit csr_scoreboard_negative;

  function new(string name = "sep_env_cfg");
    super.new(name);
  endfunction

  static function sep_env_cfg from_test_cfg(sep_test_cfg t);
    sep_env_cfg c = sep_env_cfg::type_id::create("env_cfg");
    c.sys_clk_period_ns       = t.sys_clk_period_ns;
    c.ref_clk_period_ns       = t.ref_clk_period_ns;
    c.wdt_clk_period_ns       = t.wdt_clk_period_ns;
    c.entropy_clk_period_ns   = t.entropy_clk_period_ns;
    c.axi_timeout_cycles      = t.axi_timeout_cycles;
    c.csr_scoreboard_negative = t.csr_scoreboard_negative;
    c.required_features       = t.required_features;
    return c;
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "sys_clk_period_ns=%0.2f ref_clk_period_ns=%0.1f %s wdt_clk_period_ns=%0d entropy_clk_period_ns=%0d axi_timeout_cycles=%0d",
        sys_clk_period_ns,
        ref_clk_period_ns,
        super.convert2string(),
        wdt_clk_period_ns,
        entropy_clk_period_ns,
        axi_timeout_cycles
    );
  endfunction

endclass : sep_env_cfg
