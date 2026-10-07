// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP environment configuration, derived from dtp_test_cfg and read by
// dtp_env: the chosen clock and TCK timing, responder memory geometry and
// response USER seed, the downstream STAP attach mask, the scoreboard
// features that must compare, and the evidence policy of every shared-VIP
// recorder the env builds. The env fills each VIP config from this object
// and publishes the clock period on dtp_tb_if. Never randomized. The cocotb
// twin is env/dtp_env_cfg.py.

class dtp_env_cfg extends ocah_env_cfg;
  `uvm_object_utils(dtp_env_cfg)

  // Primary TAP TCK half period, in nanoseconds.
  int unsigned tck_half_period_ns = 50;
  // Memory footprint of every AXI responder (addresses wrap).
  int unsigned axi_mem_bytes = DtpJ2aTargetMemBytes;
  // Seed of the SMC fabric responder's BUSER and RUSER draws.
  int unsigned resp_user_seed;
  // Downstream STAP TAPs attached for this run (dtp_stap_ds_name order).
  bit [DtpStapCount-1:0] stap_ds_attach_mask = '0;
  // TAP FSM checker: a JTAG-free run is legitimate only for the
  // cross-trigger group.
  bit jtag_activity_required = 1'b1;
  // Negative validation of the jtag2axi_req reference model: every
  // predicted address is corrupted, so the scoreboard pairing must fail.
  bit jtag2axi_ref_model_negative;
  // Evidence policy of the aggregate JTAG recorder and of the passive AXI
  // recorders keyed by bridge name.
  dtp_evidence_policy_t jtag_policy;
  dtp_evidence_policy_t axi_policy[string];

  function new(string name = "dtp_env_cfg");
    super.new(name);
  endfunction

  static function dtp_env_cfg from_test_cfg(dtp_test_cfg t);
    dtp_env_cfg c = dtp_env_cfg::type_id::create("env_cfg");
    c.clk_period_ns          = t.sys_clk_period_ns;
    c.tck_half_period_ns     = t.tck_period_ns / 2;
    c.resp_user_seed         = ocah_rng::salted_seed(t.seed, "resp_user");
    c.stap_ds_attach_mask    = t.stap_ds_attach_mask;
    c.jtag_activity_required = t.jtag_activity_required;
    c.jtag2axi_ref_model_negative = t.jtag2axi_ref_model_negative;
    c.jtag_policy            = t.jtag_policy;
    c.axi_policy             = t.axi_policy;
    c.required_features      = t.required_features;
    return c;
  endfunction

  // Policy of one passive AXI recorder; an unarmed bridge gets the
  // inert default.
  function dtp_evidence_policy_t axi_policy_for(string target);
    dtp_evidence_policy_t none;
    none.require_checks = 1'b0;
    return axi_policy.exists(target) ? axi_policy[target] : none;
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s tck_half_period_ns=%0d stap_ds_attach=0b%04b jtag_activity=%0d",
        super.convert2string(),
        tck_half_period_ns,
        stap_ds_attach_mask,
        jtag_activity_required
    );
  endfunction

endclass : dtp_env_cfg
