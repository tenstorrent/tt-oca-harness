// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU SV-UVM environment: composes, drives nothing, checks no protocol. It
// reads smu_env_cfg, the SMU-local smu_tb_if, and the embedded DTP's
// dtp_tb_if from uvm_config_db, sets the harness clock periods on the SMU
// TB interface, fills the shared-VIP configs and publishes them to the
// agents' subtrees, and builds:
//
//   * the active ocah_jtag_master_env on the primary TAP (the VIP's
//     commercial-overridable unit) and the smu_virtual_sequencer that
//     exposes its sequencer to the scenario virtual sequences;
//   * the memory-backed, fault-capable ocah_axi_slave_agent that answers the
//     outbound SMN AXI4 boundary on the ocah_axi_if the harness publishes as
//     axi_out_vif; its slave sequence rides the virtual sequencer;
//   * one passive ocah_axi_env, monitor only, on the DTP's SMC-fabric
//     JTAG2AXI port (dtp_smc_dbg_vif), the observed side of the embedded
//     DTP's jtag2axi_req feature and the completion source of its bridge
//     models;
//   * the checking of the embedded DTP with the DTP bench's own components,
//     reused unchanged: dtp_ir_decode_ref_model, dtp_idcode_ref_model,
//     dtp_bypass_ref_model, dtp_jtag2axi_req_ref_model and
//     dtp_jtag2axi_status_ref_model on the JTAG event, scan and bridge-port
//     streams, the dtp_tap_fsm_checker invariant subscriber, and (inside
//     smu_scoreboard) dtp_scoreboard pairing the streams. They read the
//     embedded DTP through dtp_tb_if, which the harness wires from the DTP
//     instance the same way the DTP bench wires its own top, and their
//     dtp_env_cfg is derived here from the SMU cfg;
//   * the SMU-level reference models (smu_ic_reset_tdr_ref_model,
//     smu_debug_control_tdr_ref_model on the scan stream;
//     smu_boot_gate_ref_model on the smu_reset_pin_monitor stream), the VIP
//     scan builder they and the DTP models consume, the env-owned aggregate
//     ocah_jtag_checker finalized once in check_phase, and the always-on
//     smu_scoreboard.
//
// The IDCODE the embedded reference model predicts comes from the SMU
// configuration (smu_types), corrupted under the documented negative hook.
// The cocotb twin is cocotb/env/smu_env.py.

class smu_env extends ocah_env;
  `uvm_component_utils(smu_env)

  smu_env_cfg       cfg;
  virtual smu_tb_if tb_vif;
  virtual dtp_tb_if dtp_tb_vif;

  // Primary TAP: shared VIP master env on the ocah_jtag_if published by the harness.
  ocah_jtag_master_config m_jtag_cfg;
  ocah_jtag_master_env    m_jtag_env;

  // Outbound SMN AXI4: the shared VIP responder on the ocah_axi_if the
  // struct bridge feeds in the harness.
  ocah_axi_slave_config m_axi_out_slave_cfg;
  ocah_axi_slave_agent  m_axi_out_slave_agent;

  // SMC-fabric JTAG2AXI port of the embedded DTP: passive observation.
  ocah_axi_config m_dtp_smc_dbg_cfg;
  ocah_axi_env    m_dtp_smc_dbg_env;

  // Observation and evidence: VIP scan reconstruction, aggregate JTAG
  // recorder, the reset-release monitor.
  ocah_jtag_scan_builder m_scan_builder;
  ocah_jtag_checker      m_jtag_checker;
  smu_reset_pin_monitor  m_pin_monitor;

  // Embedded DTP checking, one DTP reference model per scoreboard feature
  // and the DTP TAP FSM invariant checker, on a dtp_env_cfg derived here.
  dtp_env_cfg                   m_dtp_cfg;
  dtp_ir_decode_ref_model       m_dtp_ir_decode_ref_model;
  dtp_idcode_ref_model          m_dtp_idcode_ref_model;
  dtp_bypass_ref_model          m_dtp_bypass_ref_model;
  dtp_jtag2axi_req_ref_model    m_dtp_jtag2axi_req_ref_model;
  dtp_jtag2axi_status_ref_model m_dtp_jtag2axi_status_ref_model;
  dtp_tap_fsm_checker           m_dtp_fsm_checker;

  // SMU-level reference models.
  smu_ic_reset_tdr_ref_model      m_ic_reset_tdr_ref_model;
  smu_debug_control_tdr_ref_model m_debug_control_tdr_ref_model;
  smu_boot_gate_ref_model         m_boot_gate_ref_model;

  // Always-on verdict point and the virtual sequencer every pass runs on.
  smu_scoreboard        m_scoreboard;
  smu_virtual_sequencer m_vseqr;

  function new(string name = "smu_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smu_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smu_env_cfg `env_cfg` not found in uvm_config_db")
    if (!uvm_config_db#(virtual smu_tb_if)::get(this, "", "tb_vif", tb_vif))
      `uvm_fatal(get_type_name(), "virtual smu_tb_if `tb_vif` not found in uvm_config_db")
    if (!uvm_config_db#(virtual dtp_tb_if)::get(this, "", "dtp_tb_vif", dtp_tb_vif))
      `uvm_fatal(get_type_name(), "virtual dtp_tb_if `dtp_tb_vif` not found in uvm_config_db")
    tb_vif.ref_clk_period_ns     = cfg.ref_clk_period_ns;
    tb_vif.smu_clk_period_ns     = cfg.clk_period_ns;
    tb_vif.periph_clk_period_ns  = cfg.periph_clk_period_ns;
    tb_vif.sep_wdt_clk_period_ns = cfg.sep_wdt_clk_period_ns;
    `uvm_info(get_type_name(), {"env cfg: ", cfg.convert2string()}, UVM_MEDIUM)

    build_dtp_cfg();
    build_jtag_master();
    build_axi_out_slave();
    build_dtp_smc_dbg_monitor();
    build_checking();
    m_vseqr = smu_virtual_sequencer::type_id::create("m_vseqr", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    string dbg_source = m_dtp_smc_dbg_env.m_monitor.get_full_name();
    super.connect_phase(phase);
    m_vseqr.m_jtag_seqr         = m_jtag_env.m_sequencer;
    m_vseqr.m_axi_out_slave_seq = m_axi_out_slave_agent.seq;
    // Per-TCK events: scan reconstruction, the FSM invariant, and the
    // instruction tracking of every reference model.
    m_jtag_env.event_ap.connect(m_scan_builder.analysis_export);
    m_jtag_env.event_ap.connect(m_dtp_fsm_checker.analysis_export);
    m_jtag_env.event_ap.connect(m_dtp_ir_decode_ref_model.analysis_export);
    m_jtag_env.event_ap.connect(m_dtp_idcode_ref_model.event_export);
    m_jtag_env.event_ap.connect(m_dtp_bypass_ref_model.event_export);
    m_jtag_env.event_ap.connect(m_dtp_jtag2axi_req_ref_model.event_export);
    m_jtag_env.event_ap.connect(m_dtp_jtag2axi_status_ref_model.event_export);
    m_jtag_env.event_ap.connect(m_ic_reset_tdr_ref_model.event_export);
    m_jtag_env.event_ap.connect(m_debug_control_tdr_ref_model.event_export);
    // Reconstructed scans: IR scans supply the instruction; DR scans are
    // the observed side of idcode, bypass, jtag2axi_status and the two TDR
    // features, and the requests the bridge models decode.
    m_scan_builder.scan_ap.connect(m_dtp_ir_decode_ref_model.scan_export);
    m_scan_builder.scan_ap.connect(m_dtp_idcode_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_dtp_bypass_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_dtp_jtag2axi_req_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_dtp_jtag2axi_status_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_ic_reset_tdr_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_debug_control_tdr_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.dtp_idcode_observed_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.dtp_bypass_observed_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.dtp_jtag2axi_status_observed_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.tdr_observed_export);
    m_dtp_ir_decode_ref_model.expected_ap.connect(m_scoreboard.dtp_ir_decode_expected_export);
    m_dtp_idcode_ref_model.expected_ap.connect(m_scoreboard.dtp_idcode_expected_export);
    m_dtp_bypass_ref_model.expected_ap.connect(m_scoreboard.dtp_bypass_expected_export);
    m_dtp_jtag2axi_req_ref_model.expected_ap.connect(m_scoreboard.dtp_jtag2axi_req_expected_export);
    m_dtp_jtag2axi_status_ref_model.expected_ap.connect(
        m_scoreboard.dtp_jtag2axi_status_expected_export);
    m_ic_reset_tdr_ref_model.expected_ap.connect(m_scoreboard.ic_reset_expected_export);
    m_debug_control_tdr_ref_model.expected_ap.connect(m_scoreboard.debug_control_expected_export);
    // The bridge port: its monitor publishes the observed side of
    // jtag2axi_req and the completions both bridge models consume.
    m_dtp_jtag2axi_req_ref_model.bind_port("smc_axi", dbg_source);
    m_dtp_jtag2axi_status_ref_model.bind_port("smc_axi", dbg_source);
    m_dtp_smc_dbg_env.item_ap.connect(m_dtp_jtag2axi_req_ref_model.axi_export);
    m_dtp_smc_dbg_env.item_ap.connect(m_dtp_jtag2axi_status_ref_model.axi_export);
    m_dtp_smc_dbg_env.item_ap.connect(m_scoreboard.dtp_jtag2axi_req_observed_export);
    // Reset releases: the observed side of boot_gate and its predictor.
    m_pin_monitor.item_ap.connect(m_boot_gate_ref_model.analysis_export);
    m_pin_monitor.item_ap.connect(m_scoreboard.pin_observed_export);
    m_boot_gate_ref_model.expected_ap.connect(m_scoreboard.boot_gate_expected_export);
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    m_dtp_fsm_checker.report_evidence();
    m_jtag_checker.finalize(cfg.jtag_policy.require_checks);
  endfunction

  // ------------------------------------------------------------------
  // Composition helpers (build_phase).
  // ------------------------------------------------------------------

  // The embedded DTP components read a dtp_env_cfg: the TCK timing they
  // need, the negative hook of the bridge request model, and the required
  // features the SMU scoreboard does not own itself. Published to the whole
  // subtree; the uvm_config_db is keyed by type, so it does not collide with
  // the smu_env_cfg of the same field name.
  protected function void build_dtp_cfg();
    m_dtp_cfg = dtp_env_cfg::type_id::create("m_dtp_cfg");
    m_dtp_cfg.clk_period_ns              = cfg.clk_period_ns;
    m_dtp_cfg.tck_half_period_ns         = cfg.tck_half_period_ns;
    m_dtp_cfg.jtag2axi_ref_model_negative = cfg.j2a_ref_model_negative;
    foreach (cfg.required_features[i])
      if (!smu_scoreboard::owns_feature(cfg.required_features[i]))
        m_dtp_cfg.required_features.push_back(cfg.required_features[i]);
    uvm_config_db#(dtp_env_cfg)::set(this, "*", "env_cfg", m_dtp_cfg);
  endfunction

  protected function void build_jtag_master();
    m_jtag_cfg = ocah_jtag_master_config::type_id::create("m_jtag_cfg");
    if (!uvm_config_db#(virtual ocah_jtag_if)::get(this, "", "jtag_vif", m_jtag_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not found in uvm_config_db")
    m_jtag_cfg.is_active       = UVM_ACTIVE;
    m_jtag_cfg.en_monitor      = 1'b1;  // every check rides the OCAH event stream
    m_jtag_cfg.tck_half_period = cfg.tck_half_period_ns * 1ns;
    uvm_config_db#(ocah_jtag_master_config)::set(this, "m_jtag_env*", "cfg", m_jtag_cfg);
    m_jtag_env = ocah_jtag_master_env::type_id::create("m_jtag_env", this);
  endfunction

  // The crossbar's ext_out geometry (smu_axi_xbar_pkg axi_out_*) is stated on
  // the config; the interface keeps its default widths.
  protected function void build_axi_out_slave();
    m_axi_out_slave_cfg = ocah_axi_slave_config::type_id::create("m_axi_out_slave_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "axi_out_vif", m_axi_out_slave_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `axi_out_vif` not found in uvm_config_db")
    m_axi_out_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    m_axi_out_slave_cfg.addr_width = smu_axi_xbar_pkg::XbarAddrWidth;
    m_axi_out_slave_cfg.data_width = smu_axi_xbar_pkg::XbarDataWidth;
    m_axi_out_slave_cfg.id_width   = smu_axi_xbar_pkg::XbarOutputIdW;
    m_axi_out_slave_cfg.mem_bytes  = cfg.axi_out_mem_bytes;
    m_axi_out_slave_cfg.name_tag   = "smu_axi_out";
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_axi_out_slave_agent*", "slave_cfg",
                                               m_axi_out_slave_cfg);
    m_axi_out_slave_agent = ocah_axi_slave_agent::type_id::create("m_axi_out_slave_agent", this);
  endfunction

  // The SMC-fabric JTAG2AXI port geometry is the DTP's smc_jtag AXI4 type
  // (smu.sv: smc_pkg::smc_jtag_56_64_2_12_axi_req_t). Monitor only: the
  // VIP's memory-shadow reference model cannot describe the SMC behind the
  // bridge; the embedded DTP's jtag2axi features own the contract.
  protected function void build_dtp_smc_dbg_monitor();
    m_dtp_smc_dbg_cfg = ocah_axi_config::type_id::create("m_dtp_smc_dbg_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "dtp_smc_dbg_vif", m_dtp_smc_dbg_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `dtp_smc_dbg_vif` not found in uvm_config_db")
    m_dtp_smc_dbg_cfg.protocol      = OCAH_AXI_PROTO_AXI4;
    m_dtp_smc_dbg_cfg.addr_width    = SmuSmcJ2aAddrBits;
    m_dtp_smc_dbg_cfg.data_width    = SmuSmcJ2aDataBits;
    m_dtp_smc_dbg_cfg.id_width      = 2;
    m_dtp_smc_dbg_cfg.name_tag      = "smu_dtp_smc_dbg";
    m_dtp_smc_dbg_cfg.en_monitor    = 1'b1;
    m_dtp_smc_dbg_cfg.en_ref_model  = 1'b0;
    m_dtp_smc_dbg_cfg.en_scoreboard = 1'b0;
    m_dtp_smc_dbg_cfg.en_cov        = 1'b0;
    uvm_config_db#(ocah_axi_config)::set(this, "m_dtp_smc_dbg_env*", "cfg", m_dtp_smc_dbg_cfg);
    m_dtp_smc_dbg_env = ocah_axi_env::type_id::create("m_dtp_smc_dbg_env", this);
  endfunction

  protected function void build_checking();
    m_jtag_checker = ocah_jtag_checker::type_id::create("m_jtag_checker");
    m_jtag_checker.name_tag     = "smu_jtag";
    m_jtag_checker.required_ids = cfg.jtag_policy.required_ids;

    m_scan_builder = ocah_jtag_scan_builder::type_id::create("m_scan_builder", this);

    m_pin_monitor = smu_reset_pin_monitor::type_id::create("m_pin_monitor", this);
    m_pin_monitor.tb_vif = tb_vif;

    build_dtp_reference_models();
    build_smu_reference_models();

    m_dtp_fsm_checker = dtp_tap_fsm_checker::type_id::create("m_dtp_fsm_checker", this);
    m_dtp_fsm_checker.tb_vif           = dtp_tb_vif;
    m_dtp_fsm_checker.evidence         = m_jtag_checker;
    m_dtp_fsm_checker.require_activity = 1'b1;

    m_scoreboard = smu_scoreboard::type_id::create("m_scoreboard", this);
    m_scoreboard.dtp_tb_vif = dtp_tb_vif;
  endfunction

  // The DTP bench's reference models on the embedded DTP: each reads the
  // DTP TB interface for the reset counters it re-baselines on; the IDCODE
  // model predicts the SMU-configured device identification.
  protected function void build_dtp_reference_models();
    m_dtp_ir_decode_ref_model =
        dtp_ir_decode_ref_model::type_id::create("m_dtp_ir_decode_ref_model", this);
    m_dtp_ir_decode_ref_model.tb_vif = dtp_tb_vif;
    m_dtp_idcode_ref_model = dtp_idcode_ref_model::type_id::create("m_dtp_idcode_ref_model", this);
    m_dtp_idcode_ref_model.tb_vif          = dtp_tb_vif;
    m_dtp_idcode_ref_model.expected_idcode = smu_ptap_expected_idcode(cfg.ptap_idcode_negative);
    if (cfg.ptap_idcode_negative)
      `uvm_info(get_type_name(), $sformatf(
                "NEGATIVE VALIDATION: idcode reference model predicts 0x%08h instead of 0x%08h",
                m_dtp_idcode_ref_model.expected_idcode,
                SmuPtapIdcode
                ), UVM_LOW)
    m_dtp_bypass_ref_model = dtp_bypass_ref_model::type_id::create("m_dtp_bypass_ref_model", this);
    m_dtp_bypass_ref_model.tb_vif = dtp_tb_vif;
    m_dtp_jtag2axi_req_ref_model =
        dtp_jtag2axi_req_ref_model::type_id::create("m_dtp_jtag2axi_req_ref_model", this);
    m_dtp_jtag2axi_req_ref_model.tb_vif   = dtp_tb_vif;
    m_dtp_jtag2axi_req_ref_model.negative = cfg.j2a_ref_model_negative;
    if (cfg.j2a_ref_model_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: jtag2axi_req reference model predicts corrupted addresses",
                UVM_LOW)
    m_dtp_jtag2axi_status_ref_model =
        dtp_jtag2axi_status_ref_model::type_id::create("m_dtp_jtag2axi_status_ref_model", this);
    m_dtp_jtag2axi_status_ref_model.tb_vif = dtp_tb_vif;
  endfunction

  protected function void build_smu_reference_models();
    m_ic_reset_tdr_ref_model =
        smu_ic_reset_tdr_ref_model::type_id::create("m_ic_reset_tdr_ref_model", this);
    m_ic_reset_tdr_ref_model.dtp_tb_vif = dtp_tb_vif;
    m_debug_control_tdr_ref_model =
        smu_debug_control_tdr_ref_model::type_id::create("m_debug_control_tdr_ref_model", this);
    m_debug_control_tdr_ref_model.dtp_tb_vif = dtp_tb_vif;
    m_boot_gate_ref_model = smu_boot_gate_ref_model::type_id::create("m_boot_gate_ref_model", this);
  endfunction

endclass : smu_env
