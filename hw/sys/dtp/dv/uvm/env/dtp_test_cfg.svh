// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP test configuration: the highest configuration level and the only
// object the seed touches. Randomizes the system-clock and TCK periods from
// the runner seed (cocotb DtpEnvCfg.randomize_timing parity: 10..100 ns
// and 100..1000 ns, even so both half periods are whole nanoseconds),
// carries the knob-derived controls (the cocotb environment knobs of the
// same names), the negative-validation switches, the downstream STAP attach
// mask and host segment attach, the scoreboard features a test requires, and
// the shared-VIP evidence policy per recorder. The base test fills the knobs
// (read_knobs), seeds and randomizes it once, then derives dtp_env_cfg from
// it. In the cocotb realization, DtpEnvCfg.randomize_timing
// (env/dtp_env_cfg.py) owns the timing draw and each test reads its knobs
// through OcahKnobs.

class dtp_test_cfg extends ocah_test_cfg;
  `uvm_object_utils(dtp_test_cfg)

  // --- randomized timing --------------------------------------------------
  rand int unsigned sys_clk_period_ns;
  rand int unsigned tck_period_ns;
  constraint sys_clk_c {
    sys_clk_period_ns inside {[10 : 100]};
    sys_clk_period_ns % 2 == 0;
  }
  constraint tck_c {
    tck_period_ns inside {[100 : 1000]};
    tck_period_ns % 2 == 0;
  }

  // --- knob-derived controls (cocotb env knob names) ---------------------
  // +DTP_IDCODE_READS_PER_LOOP: IDCODE reads per pass (minimum 1).
  int unsigned idcode_reads_per_loop = 4;
  // +DTP_RAND_WALKS: random TMS walks per sanity pass.
  int unsigned rand_walks = 16;
  // +DTP_DBG_DISABLE_MULTI_HOT_ROWS: multi-hot rows of the dbg_disable
  // matrices (scan matrix default 6, JTAG2AXI matrix default 11).
  int unsigned scan_matrix_multi_hot_rows     = 6;
  int unsigned jtag2axi_matrix_multi_hot_rows = 11;

  // --- negative-validation switches (must FAIL the run when set) ----------
  bit family_checker_negative;   // +DTP_JTAG_FAMILY_CHECKER_NEGATIVE
  bit tap_checker_negative;      // +DTP_JTAG_TAP_CHECKER_NEGATIVE
  bit axi_scoreboard_negative;   // +DTP_AXI_SCOREBOARD_NEGATIVE
  bit xtrig_checker_negative;    // +DTP_XTRIG_CHECKER_NEGATIVE
  // +DTP_XTRIG_NEGATIVE_CHECK=<n>: index of the cross-trigger evidence ID
  // whose observed values are corrupted (dtp_xtrig_base_test_seq table);
  // 0 = off.
  int unsigned xtrig_negative_check;
  bit j2a_geometry_negative;     // +DTP_J2A_GEOMETRY_NEGATIVE
  bit j2a_status_bit_negative;   // +DTP_J2A_STATUS_BIT_NEGATIVE
  bit j2a_bus_req_negative;      // +DTP_J2A_BUS_REQ_NEGATIVE
  bit j2a_orphan_negative;       // +DTP_J2A_ORPHAN_NEGATIVE
  bit jtag2axi_ref_model_negative;  // +DTP_J2A_REF_MODEL_NEGATIVE
  bit xtrig_csr_ref_model_negative;  // +DTP_XTRIG_CSR_REF_MODEL_NEGATIVE
  bit xtrig_decode_ref_model_negative;  // +DTP_XTRIG_DECODE_REF_MODEL_NEGATIVE

  // --- bench topology -------------------------------------------------------
  // Bit i splices the shared JTAG slave device behind STAP host port i
  // (dtp_stap_ds_name order: io, smc, sep, extra0); 0 keeps the loopback.
  bit [DtpStapCount-1:0] stap_ds_attach_mask = '0;
  // 1 places the tb_top host segment behind the extended STAP host scan
  // interface; 0 keeps the host scan loopback.
  bit stap_host_segment_attach = 1'b0;

  // --- evidence policy -----------------------------------------------------
  // JTAG scenarios must show TCK activity; the cross-trigger group drives
  // no JTAG and clears this.
  bit jtag_activity_required = 1'b1;
  // Aggregate JTAG recorder (env-owned ocah_jtag_checker) and the passive
  // AXI recorders keyed by bridge name (smc_axi, smc_otp, sep_otp).
  dtp_evidence_policy_t jtag_policy;
  dtp_evidence_policy_t axi_policy[string];

  function new(string name = "dtp_test_cfg");
    super.new(name);
    require_feature(DtpFeatureIrDecode);
  endfunction

  // Fill the knob-derived controls through the one knob accessor.
  function void read_knobs();
    idcode_reads_per_loop = ocah_knobs::get_int_min("DTP_IDCODE_READS_PER_LOOP", 4, 1);
    rand_walks            = ocah_knobs::get_int_min("DTP_RAND_WALKS", 16, 1);
    scan_matrix_multi_hot_rows =
            ocah_knobs::get_int_min("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 6, 1);
    jtag2axi_matrix_multi_hot_rows =
            ocah_knobs::get_int_min("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 11, 1);
    family_checker_negative = ocah_knobs::is_set("DTP_JTAG_FAMILY_CHECKER_NEGATIVE");
    tap_checker_negative    = ocah_knobs::is_set("DTP_JTAG_TAP_CHECKER_NEGATIVE");
    axi_scoreboard_negative = ocah_knobs::is_set("DTP_AXI_SCOREBOARD_NEGATIVE");
    xtrig_checker_negative  = ocah_knobs::is_set("DTP_XTRIG_CHECKER_NEGATIVE");
    xtrig_negative_check    = ocah_knobs::get_int("DTP_XTRIG_NEGATIVE_CHECK", 0);
    j2a_geometry_negative   = ocah_knobs::is_set("DTP_J2A_GEOMETRY_NEGATIVE");
    j2a_status_bit_negative = ocah_knobs::is_set("DTP_J2A_STATUS_BIT_NEGATIVE");
    j2a_bus_req_negative    = ocah_knobs::is_set("DTP_J2A_BUS_REQ_NEGATIVE");
    j2a_orphan_negative     = ocah_knobs::is_set("DTP_J2A_ORPHAN_NEGATIVE");
    jtag2axi_ref_model_negative = ocah_knobs::is_set("DTP_J2A_REF_MODEL_NEGATIVE");
    xtrig_csr_ref_model_negative = ocah_knobs::is_set("DTP_XTRIG_CSR_REF_MODEL_NEGATIVE");
    xtrig_decode_ref_model_negative = ocah_knobs::is_set("DTP_XTRIG_DECODE_REF_MODEL_NEGATIVE");
  endfunction

  // Arm the aggregate JTAG recorder: zero checks or a missing ID fails.
  function void require_jtag_ids(string ids[$]);
    jtag_policy.require_checks = 1'b1;
    foreach (ids[i]) jtag_policy.required_ids.push_back(ids[i]);
  endfunction

  // Arm one passive AXI recorder by bridge name. A scenario that drives a
  // bridge must also land the scoreboard's bridge features: every launched
  // transaction paired with its JTAG request, and every status capture
  // paired with the completions behind it.
  function void require_axi_ids(string target, string ids[$]);
    if (!axi_policy.exists(target)) begin
      dtp_evidence_policy_t p;
      p.require_checks = 1'b0;
      axi_policy[target] = p;
    end
    axi_policy[target].require_checks = 1'b1;
    foreach (ids[i]) axi_policy[target].required_ids.push_back(ids[i]);
    require_feature(DtpFeatureJtag2axiReq);
    require_feature(DtpFeatureJtag2axiStatus);
  endfunction

  // Whether the passive AXI recorder of `target` requires evidence ID `id`.
  function bit requires_axi_id(string target, string id);
    if (!axi_policy.exists(target)) return 1'b0;
    foreach (axi_policy[target].required_ids[i])
    if (axi_policy[target].required_ids[i] == id) return 1'b1;
    return 1'b0;
  endfunction

  // Replace the default required scoreboard features (the cross-trigger
  // group drives no JTAG, so ir_decode cannot be required there).
  function void set_required_features(string features[$]);
    required_features.delete();
    foreach (features[i]) require_feature(features[i]);
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s sys_clk_period_ns=%0d tck_period_ns=%0d stap_ds_attach=0b%04b jtag_activity=%0d",
        super.convert2string(),
        sys_clk_period_ns,
        tck_period_ns,
        stap_ds_attach_mask,
        jtag_activity_required
    );
  endfunction

endclass : dtp_test_cfg
