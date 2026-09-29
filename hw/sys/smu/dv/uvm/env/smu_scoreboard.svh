// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU scoreboard: always on, in every test, and comparing only. SMU is a
// system that integrates IPs and subsystems, so its scoreboard is the one
// verdict point over two kinds of features:
//
//   * embedded-IP features, judged by that IP's own bench scoreboard reused
//     unchanged as a child: dtp_scoreboard for the primary TAP of the
//     embedded DTP (ir_decode, idcode, bypass on the JTAG event and scan
//     streams; jtag2axi_req and jtag2axi_status on the SMC-fabric bridge's
//     scan stream and the passive monitor of its AXI port, exactly as the
//     DTP bench pairs them). The child reads its own env cfg from
//     uvm_config_db and dtp_tb_if for the observables. Streams reach it
//     through the pass-through exports below, so smu_env wires this
//     scoreboard only;
//   * SMU-level integration features, registered here on the
//     ocah_scoreboard base:
//
//     ic_reset_tdr       every full-length IC_RESET DR scan is paired with
//                        the capture smu_ic_reset_tdr_ref_model predicted
//                        from the previous update and the TAP resets seen;
//     debug_control_tdr  every DEBUG_CONTROL DR scan likewise, on the
//                        software-owned bits;
//     boot_gate          every SMC fuse-reset release observed by
//                        smu_reset_pin_monitor is paired with the gate and
//                        sense levels smu_boot_gate_ref_model requires of
//                        it.
//
// A required feature (smu_test_cfg.required_features through the env cfg)
// is routed by smu_env to the scoreboard that registers it. Expected values
// never originate here. The cocotb twin is cocotb/env/smu_scoreboard.py.

`uvm_analysis_imp_decl(_smu_tdr_observed)
`uvm_analysis_imp_decl(_smu_ic_reset_expected)
`uvm_analysis_imp_decl(_smu_debug_control_expected)
`uvm_analysis_imp_decl(_smu_pin_observed)
`uvm_analysis_imp_decl(_smu_boot_gate_expected)

class smu_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(smu_scoreboard)

  smu_env_cfg cfg;
  // Handed by smu_env: the embedded DTP's TB interface (tap_state,
  // inst_decoded, reset counters) the child scoreboard reads.
  virtual dtp_tb_if dtp_tb_vif;

  // Embedded DTP: the DTP bench's scoreboard, reused as-is.
  dtp_scoreboard m_dtp_scoreboard;

  // Pass-through exports into the embedded DTP scoreboard (feature =
  // dtp_scoreboard feature): the reference models' expected streams and
  // the observed streams.
  uvm_analysis_export #(dtp_expected_item)        dtp_ir_decode_expected_export;
  uvm_analysis_export #(ocah_jtag_scan_item)      dtp_idcode_observed_export;
  uvm_analysis_export #(dtp_expected_item)        dtp_idcode_expected_export;
  uvm_analysis_export #(ocah_jtag_scan_item)      dtp_bypass_observed_export;
  uvm_analysis_export #(dtp_expected_item)        dtp_bypass_expected_export;
  uvm_analysis_export #(ocah_axi_item)            dtp_jtag2axi_req_observed_export;
  uvm_analysis_export #(ocah_axi_item)            dtp_jtag2axi_req_expected_export;
  uvm_analysis_export #(ocah_jtag_scan_item)      dtp_jtag2axi_status_observed_export;
  uvm_analysis_export #(dtp_jtag2axi_status_item) dtp_jtag2axi_status_expected_export;

  // SMU-level features: the reconstructed scan stream is the observed side
  // of both TDR features; the reset-release stream that of boot_gate.
  uvm_analysis_imp_smu_tdr_observed #(ocah_jtag_scan_item, smu_scoreboard) tdr_observed_export;
  uvm_analysis_imp_smu_ic_reset_expected #(smu_tdr_expected_item, smu_scoreboard)
      ic_reset_expected_export;
  uvm_analysis_imp_smu_debug_control_expected #(smu_tdr_expected_item, smu_scoreboard)
      debug_control_expected_export;
  uvm_analysis_imp_smu_pin_observed #(smu_pin_event_item, smu_scoreboard) pin_observed_export;
  uvm_analysis_imp_smu_boot_gate_expected #(smu_pin_event_item, smu_scoreboard)
      boot_gate_expected_export;

  function new(string name = "smu_scoreboard", uvm_component parent = null);
    super.new(name, parent);
    name_tag = "smu_scoreboard";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smu_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smu_env_cfg `env_cfg` not found in uvm_config_db")
    if (dtp_tb_vif == null)
      `uvm_fatal(get_type_name(), "virtual dtp_tb_if `dtp_tb_vif` not set by the env")
    dtp_ir_decode_expected_export       = new("dtp_ir_decode_expected_export", this);
    dtp_idcode_observed_export          = new("dtp_idcode_observed_export", this);
    dtp_idcode_expected_export          = new("dtp_idcode_expected_export", this);
    dtp_bypass_observed_export          = new("dtp_bypass_observed_export", this);
    dtp_bypass_expected_export          = new("dtp_bypass_expected_export", this);
    dtp_jtag2axi_req_observed_export    = new("dtp_jtag2axi_req_observed_export", this);
    dtp_jtag2axi_req_expected_export    = new("dtp_jtag2axi_req_expected_export", this);
    dtp_jtag2axi_status_observed_export = new("dtp_jtag2axi_status_observed_export", this);
    dtp_jtag2axi_status_expected_export = new("dtp_jtag2axi_status_expected_export", this);
    tdr_observed_export           = new("tdr_observed_export", this);
    ic_reset_expected_export      = new("ic_reset_expected_export", this);
    debug_control_expected_export = new("debug_control_expected_export", this);
    pin_observed_export           = new("pin_observed_export", this);
    boot_gate_expected_export     = new("boot_gate_expected_export", this);
    add_feature(SmuFeatureIcResetTdr);
    add_feature(SmuFeatureDebugControlTdr);
    add_feature(SmuFeatureBootGate);
    foreach (cfg.required_features[i])
      if (has_feature(cfg.required_features[i])) require_feature(cfg.required_features[i]);
    m_dtp_scoreboard = dtp_scoreboard::type_id::create("m_dtp_scoreboard", this);
    m_dtp_scoreboard.tb_vif   = dtp_tb_vif;
    m_dtp_scoreboard.name_tag = "smu_dtp_scoreboard";
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    dtp_ir_decode_expected_export.connect(m_dtp_scoreboard.ir_decode_expected_export);
    dtp_idcode_observed_export.connect(m_dtp_scoreboard.idcode_observed_export);
    dtp_idcode_expected_export.connect(m_dtp_scoreboard.idcode_expected_export);
    dtp_bypass_observed_export.connect(m_dtp_scoreboard.bypass_observed_export);
    dtp_bypass_expected_export.connect(m_dtp_scoreboard.bypass_expected_export);
    dtp_jtag2axi_req_observed_export.connect(m_dtp_scoreboard.jtag2axi_req_observed_export);
    dtp_jtag2axi_req_expected_export.connect(m_dtp_scoreboard.jtag2axi_req_expected_export);
    dtp_jtag2axi_status_observed_export.connect(m_dtp_scoreboard.jtag2axi_status_observed_export);
    dtp_jtag2axi_status_expected_export.connect(m_dtp_scoreboard.jtag2axi_status_expected_export);
  endfunction

  // A feature registered here or in the child: the env routes each required
  // name to the scoreboard that owns it.
  static function bit owns_feature(string feature);
    return (feature == SmuFeatureIcResetTdr) || (feature == SmuFeatureDebugControlTdr) ||
        (feature == SmuFeatureBootGate);
  endfunction

  // Comparison and mismatch counts of any feature, this scoreboard's or the
  // embedded DTP's (the scenario activity floor reads them).
  function int unsigned feature_compare_count(string feature);
    if (has_feature(feature)) return compare_count(feature);
    return m_dtp_scoreboard.compare_count(feature);
  endfunction

  function int unsigned feature_mismatch_count(string feature);
    if (has_feature(feature)) return mismatch_count(feature);
    return m_dtp_scoreboard.mismatch_count(feature);
  endfunction

  // ------------------------------------------------------------------
  // Streams: every DR scan is an observation of both TDR features (the
  // models publish one item per scan, contract or not, so the queues stay
  // in lockstep); every reset release an observation of boot_gate.
  // ------------------------------------------------------------------

  function void write_smu_tdr_observed(ocah_jtag_scan_item t);
    push_observed(SmuFeatureIcResetTdr, t);
    push_observed(SmuFeatureDebugControlTdr, t);
  endfunction

  function void write_smu_ic_reset_expected(smu_tdr_expected_item t);
    push_expected(SmuFeatureIcResetTdr, t);
  endfunction

  function void write_smu_debug_control_expected(smu_tdr_expected_item t);
    push_expected(SmuFeatureDebugControlTdr, t);
  endfunction

  function void write_smu_pin_observed(smu_pin_event_item t);
    push_observed(SmuFeatureBootGate, t);
  endfunction

  function void write_smu_boot_gate_expected(smu_pin_event_item t);
    push_expected(SmuFeatureBootGate, t);
  endfunction

  // ------------------------------------------------------------------
  // Pair verdicts.
  // ------------------------------------------------------------------

  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    if (feature == SmuFeatureIcResetTdr || feature == SmuFeatureDebugControlTdr)
      compare_tdr_pair(feature, observed, expected);
    else if (feature == SmuFeatureBootGate) compare_boot_gate_pair(observed, expected);
    else super.compare_pair(feature, observed, expected);
  endfunction

  // The scan's shifted-out bits, as a wide vector, under the expected mask.
  protected function void compare_tdr_pair(string feature, uvm_object observed,
                                           uvm_object expected);
    smu_tdr_expected_item exp;
    ocah_jtag_scan_item   obs;
    bit [255:0]           tdo = '0;
    if (!$cast(exp, expected))
      `uvm_fatal(get_type_name(), {feature, ": expected item is not an smu_tdr_expected_item"})
    if (!$cast(obs, observed))
      `uvm_fatal(get_type_name(), {feature, ": observed item is not an ocah_jtag_scan_item"})
    if (!exp.compare) return;
    foreach (obs.tdo_bits[i]) if (i < 256) tdo[i] = obs.tdo_bits[i];
    record_compare(feature, ((tdo & exp.mask) === (exp.expected & exp.mask)),
                   $sformatf("0x%0h", exp.expected & exp.mask), $sformatf("0x%0h", tdo & exp.mask),
                   $sformatf("%s bits=%0d mask=0x%0h", exp.context_s, obs.bit_count, exp.mask));
  endfunction

  // One fuse-reset release: the gate open and the sense complete in the
  // clock the release was observed.
  protected function void compare_boot_gate_pair(uvm_object observed, uvm_object expected);
    smu_pin_event_item exp, obs;
    if (!$cast(exp, expected))
      `uvm_fatal(get_type_name(), "boot_gate: expected item is not an smu_pin_event_item")
    if (!$cast(obs, observed))
      `uvm_fatal(get_type_name(), "boot_gate: observed item is not an smu_pin_event_item")
    if (!exp.compare) return;
    record_compare(SmuFeatureBootGate, (obs.kind == exp.kind) &&
                   (obs.ext_boot_seq_done == exp.ext_boot_seq_done) &&
                   (obs.fuse_sense_done == exp.fuse_sense_done), $sformatf(
                   "gate=%0b sense_done=%0b", exp.ext_boot_seq_done, exp.fuse_sense_done),
                   $sformatf("gate=%0b sense_done=%0b", obs.ext_boot_seq_done,
                             obs.fuse_sense_done), $sformatf("%s @%0t", exp.context_s,
                                                             obs.timestamp));
  endfunction

endclass : smu_scoreboard
