// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU environment configuration, derived from smu_test_cfg and read by
// smu_env: the chosen clock and TCK timing, the scoreboard features that
// must compare, the negative-validation switches the reference models
// honor, the aggregate JTAG evidence policy, and the memory footprint of the
// outbound SMN responder. The env fills the VIP configs from this object and
// publishes the clock periods on smu_tb_if. Never randomized. The cocotb
// twin is cocotb_wrapper/env/smu_env_cfg.py.

class smu_env_cfg extends ocah_env_cfg;
  `uvm_object_utils(smu_env_cfg)

  // clk_period_ns (base) is the smu clock; the other domains follow.
  int unsigned ref_clk_period_ns     = 10;
  int unsigned periph_clk_period_ns  = 20;
  int unsigned sep_wdt_clk_period_ns = 100;
  // Primary TAP TCK half period, in nanoseconds.
  int unsigned tck_half_period_ns = 20;
  // Reference-model negative hooks.
  bit ptap_idcode_negative;
  bit ic_reset_tdr_negative;
  bit debug_control_tdr_negative;
  bit boot_gate_negative;
  bit j2a_ref_model_negative;
  // Evidence policy of the env-owned aggregate JTAG recorder.
  smu_evidence_policy_t jtag_policy;
  // Backing memory of the outbound SMN responder, in bytes (addresses wrap).
  int unsigned axi_out_mem_bytes = 32'h8000_0000;

  function new(string name = "smu_env_cfg");
    super.new(name);
  endfunction

  static function smu_env_cfg from_test_cfg(smu_test_cfg t);
    smu_env_cfg c = smu_env_cfg::type_id::create("env_cfg");
    c.clk_period_ns              = t.smu_clk_period_ns;
    c.ref_clk_period_ns          = t.ref_clk_period_ns;
    c.periph_clk_period_ns       = t.periph_clk_period_ns;
    c.sep_wdt_clk_period_ns      = t.sep_wdt_clk_period_ns;
    c.tck_half_period_ns         = t.tck_period_ns / 2;
    c.ptap_idcode_negative       = t.ptap_idcode_negative;
    c.ic_reset_tdr_negative      = t.ic_reset_tdr_negative;
    c.debug_control_tdr_negative = t.debug_control_tdr_negative;
    c.boot_gate_negative         = t.boot_gate_negative;
    c.j2a_ref_model_negative     = t.j2a_ref_model_negative;
    c.jtag_policy                = t.jtag_policy;
    c.required_features          = t.required_features;
    return c;
  endfunction

  virtual function string convert2string();
    return $sformatf(
        {
          "%s ref_clk_period_ns=%0d periph_clk_period_ns=%0d sep_wdt_clk_period_ns=%0d ",
          "tck_half_period_ns=%0d"
        },
        super.convert2string(),
        ref_clk_period_ns,
        periph_clk_period_ns,
        sep_wdt_clk_period_ns,
        tck_half_period_ns
    );
  endfunction

endclass : smu_env_cfg
