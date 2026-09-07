// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU scoreboard: always on, in every test, and comparing only. SMU is a
// system that integrates IPs and subsystems, so its scoreboard is the one
// verdict point over two kinds of features:
//
//   * embedded-IP features, judged by that IP's own bench scoreboard reused
//     unchanged as a child: dtp_scoreboard for the primary TAP of the
//     embedded DTP (ir_decode, idcode, bypass, ... on the JTAG event and
//     scan streams, exactly as the DTP bench pairs them). The child reads
//     its own env cfg from uvm_config_db and dtp_tb_if for the
//     observables; this class publishes both. Streams reach it through
//     the pass-through exports below, so smu_env wires this scoreboard
//     only;
//   * SMU-level integration features, registered here on the
//     ocah_scoreboard base like any bench scoreboard.
//
// A required feature (smu_test_cfg.required_features through the env cfg)
// is routed to the scoreboard that registers it; a name neither knows is a
// configuration defect (the child's registry check reports it). Expected
// values never originate here. The cocotb twin is env/smu_scoreboard.py.

class smu_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(smu_scoreboard)

  smu_env_cfg cfg;
  // Handed by smu_env: the embedded DTP's TB interface (tap_state,
  // inst_decoded, reset counters) the child scoreboard reads.
  virtual dtp_tb_if dtp_tb_vif;

  // Embedded DTP: the DTP bench's scoreboard, reused as-is.
  dtp_scoreboard m_dtp_scoreboard;
  dtp_env_cfg    m_dtp_cfg;

  // Pass-through exports into the embedded DTP scoreboard (feature =
  // dtp_scoreboard feature): the reference models' expected streams and
  // the reconstructed-scan observed streams.
  uvm_analysis_export #(dtp_expected_item)   dtp_ir_decode_expected_export;
  uvm_analysis_export #(ocah_jtag_scan_item) dtp_idcode_observed_export;
  uvm_analysis_export #(dtp_expected_item)   dtp_idcode_expected_export;
  uvm_analysis_export #(ocah_jtag_scan_item) dtp_bypass_observed_export;
  uvm_analysis_export #(dtp_expected_item)   dtp_bypass_expected_export;

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
    dtp_ir_decode_expected_export = new("dtp_ir_decode_expected_export", this);
    dtp_idcode_observed_export    = new("dtp_idcode_observed_export", this);
    dtp_idcode_expected_export    = new("dtp_idcode_expected_export", this);
    dtp_bypass_observed_export    = new("dtp_bypass_observed_export", this);
    dtp_bypass_expected_export    = new("dtp_bypass_expected_export", this);
    build_dtp_scoreboard();
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    dtp_ir_decode_expected_export.connect(m_dtp_scoreboard.ir_decode_expected_export);
    dtp_idcode_observed_export.connect(m_dtp_scoreboard.idcode_observed_export);
    dtp_idcode_expected_export.connect(m_dtp_scoreboard.idcode_expected_export);
    dtp_bypass_observed_export.connect(m_dtp_scoreboard.bypass_observed_export);
    dtp_bypass_expected_export.connect(m_dtp_scoreboard.bypass_expected_export);
  endfunction

  // The embedded DTP scoreboard with the required features routed to it:
  // every required feature this scoreboard does not register itself is the
  // child's (an unknown name fails in the child's registry check).
  protected function void build_dtp_scoreboard();
    m_dtp_cfg = dtp_env_cfg::type_id::create("m_dtp_cfg");
    foreach (cfg.required_features[i]) begin
      if (has_feature(cfg.required_features[i])) require_feature(cfg.required_features[i]);
      else m_dtp_cfg.required_features.push_back(cfg.required_features[i]);
    end
    uvm_config_db#(dtp_env_cfg)::set(this, "m_dtp_scoreboard*", "env_cfg", m_dtp_cfg);
    m_dtp_scoreboard = dtp_scoreboard::type_id::create("m_dtp_scoreboard", this);
    m_dtp_scoreboard.tb_vif   = dtp_tb_vif;
    m_dtp_scoreboard.name_tag = "smu_dtp_scoreboard";
  endfunction

endclass : smu_scoreboard
