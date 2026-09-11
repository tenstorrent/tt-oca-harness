// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive VIP-level env for one observed AXI/AXI-Lite bus: cfg-gated monitor,
// reference model, scoreboard, and optional coverage subscriber, wired
//   monitor.item_ap -> {ref_model, scoreboard.observed, cov_sub}
//   ref_model.expected_ap -> scoreboard.expected
//
// Frozen surface for adopters and commercial-VIP overrides (same contract as
// ocah_jtag_master_env): `cfg`, `item_ap` (pass-through of the monitor's stream),
// and `m_checker` (scenario-level named evidence; valid once the scoreboard is
// built). A commercial integration may subclass this env, replace the monitor,
// and keep the model/scoreboard/evidence surface intact.

class ocah_axi_env extends uvm_env;
  `uvm_component_utils(ocah_axi_env)

  ocah_axi_config cfg;
  ocah_axi_monitor    m_monitor;
  ocah_axi_ref_model  m_ref_model;
  ocah_axi_scoreboard m_scoreboard;
  ocah_axi_cov    m_cov;

  // Frozen surface.
  uvm_analysis_port #(ocah_axi_item) item_ap;
  ocah_axi_checker m_checker;

  function new(string name = "ocah_axi_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_axi_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_axi_config `cfg` not found in uvm_config_db")
    uvm_config_db#(ocah_axi_config)::set(this, "*", "cfg", cfg);
    item_ap = new("item_ap", this);
    if (cfg.en_monitor) m_monitor = ocah_axi_monitor::type_id::create("m_monitor", this);
    if (cfg.en_ref_model) m_ref_model = ocah_axi_ref_model::type_id::create("m_ref_model", this);
    if (cfg.en_scoreboard) begin
      if (!cfg.en_monitor || !cfg.en_ref_model)
        `uvm_fatal(get_type_name(),
                   "scoreboard enabled without monitor+ref_model; it will see no items")
      m_scoreboard = ocah_axi_scoreboard::type_id::create("m_scoreboard", this);
    end
    if (cfg.en_cov) m_cov = ocah_axi_cov::type_id::create("m_cov", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (m_monitor != null) begin
      m_monitor.item_ap.connect(item_ap);
      if (m_ref_model != null) m_monitor.item_ap.connect(m_ref_model.analysis_export);
      if (m_scoreboard != null) m_monitor.item_ap.connect(m_scoreboard.observed_export);
      if (m_cov != null) m_monitor.item_ap.connect(m_cov.analysis_export);
    end
    if (m_ref_model != null && m_scoreboard != null)
      m_ref_model.expected_ap.connect(m_scoreboard.expected_export);
    if (m_scoreboard != null) m_checker = m_scoreboard.m_checker;
  endfunction

endclass : ocah_axi_env
