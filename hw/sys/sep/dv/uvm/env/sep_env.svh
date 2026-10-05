// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP SV-UVM environment: composes, drives nothing, checks no protocol. It
// reads sep_env_cfg and the SEP-local sep_tb_if from uvm_config_db, sets
// the four harness clock periods on the TB interface, fills one shared-VIP
// config per port (interface, geometry, name_tag) and publishes it to that
// agent's subtree, and builds:
//
//   * the active ocah_axi_master_env driving the CPU-LSU AXI4 splice (the
//     VIP's commercial-overridable unit) and the sep_virtual_sequencer that
//     exposes its sequencer to the scenario virtual sequences;
//   * one passive ocah_axi_env on the CPU-LSU mirror interface, monitor
//     only: the VIP's memory-shadow reference model cannot describe a CSR
//     block (reset values, reserved fields, side effects), so the bench's
//     own reference models predict on its item stream;
//   * one reference model per scoreboard feature,
//     sep_cpu_ctrl_csr_ref_model on the CPU-LSU stream, and the always-on
//     sep_scoreboard pairing each feature's expected stream with the
//     observed one.
//
// The cocotb twin is cocotb/env/sep_env.py.

class sep_env extends ocah_env;
  `uvm_component_utils(sep_env)

  sep_env_cfg       cfg;
  virtual sep_tb_if tb_vif;

  // CPU-LSU initiator: shared VIP master env on the interface tb_top publishes.
  ocah_axi_master_config m_lsu_master_cfg;
  ocah_axi_master_env    m_lsu_master_env;

  // CPU-LSU observation: shared VIP passive env, monitor only.
  ocah_axi_config m_lsu_axi_cfg;
  ocah_axi_env    m_lsu_axi_env;

  // Always-on checking: one reference model per feature and the scoreboard
  // that pairs them; the virtual sequencer every pass runs on.
  sep_cpu_ctrl_csr_ref_model m_cpu_ctrl_csr_ref_model;
  sep_scoreboard             m_scoreboard;
  sep_virtual_sequencer      m_vseqr;

  function new(string name = "sep_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(sep_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "sep_env_cfg `env_cfg` not found in uvm_config_db")
    if (!uvm_config_db#(virtual sep_tb_if)::get(this, "", "tb_vif", tb_vif))
      `uvm_fatal(get_type_name(), "virtual sep_tb_if `tb_vif` not found in uvm_config_db")
    tb_vif.sys_clk_period_ns     = cfg.sys_clk_period_ns;
    tb_vif.ref_clk_period_ns     = cfg.ref_clk_period_ns;
    tb_vif.wdt_clk_period_ns     = cfg.wdt_clk_period_ns;
    tb_vif.entropy_clk_period_ns = cfg.entropy_clk_period_ns;
    `uvm_info(get_type_name(), {"env cfg: ", cfg.convert2string()}, UVM_MEDIUM)

    build_lsu_master();
    build_lsu_passive();

    m_cpu_ctrl_csr_ref_model =
        sep_cpu_ctrl_csr_ref_model::type_id::create("m_cpu_ctrl_csr_ref_model", this);
    m_cpu_ctrl_csr_ref_model.tb_vif = tb_vif;
    m_scoreboard = sep_scoreboard::type_id::create("m_scoreboard", this);

    m_vseqr = sep_virtual_sequencer::type_id::create("m_vseqr", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    m_vseqr.m_lsu_seqr = m_lsu_master_env.m_sequencer;
    m_vseqr.m_scoreboard = m_scoreboard;
    // cpu_ctrl_csr: the monitor stream feeds the reference model and the
    // scoreboard's observed side; the model's expected_ap feeds the other.
    m_lsu_axi_env.item_ap.connect(m_cpu_ctrl_csr_ref_model.analysis_export);
    m_cpu_ctrl_csr_ref_model.expected_ap.connect(m_scoreboard.csr_expected_export);
    m_lsu_axi_env.item_ap.connect(m_scoreboard.csr_observed_export);
  endfunction

  // ------------------------------------------------------------------
  // Composition helpers (build_phase).
  // ------------------------------------------------------------------

  protected function void build_lsu_master();
    m_lsu_master_cfg = ocah_axi_master_config::type_id::create("m_lsu_master_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "lsu_master_vif", m_lsu_master_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `lsu_master_vif` not found in uvm_config_db")
    m_lsu_master_cfg.protocol       = OCAH_AXI_PROTO_AXI4;
    m_lsu_master_cfg.addr_width     = SepLsuAddrWidth;
    m_lsu_master_cfg.data_width     = SepLsuDataWidth;
    m_lsu_master_cfg.id_width       = SepLsuIdWidth;
    m_lsu_master_cfg.timeout_cycles = cfg.axi_timeout_cycles;
    m_lsu_master_cfg.name_tag       = "sep_lsu_master";
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_lsu_master_env*", "cfg", m_lsu_master_cfg);
    m_lsu_master_env = ocah_axi_master_env::type_id::create("m_lsu_master_env", this);
  endfunction

  protected function void build_lsu_passive();
    m_lsu_axi_cfg = ocah_axi_config::type_id::create("m_lsu_axi_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "lsu_axi_vif", m_lsu_axi_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `lsu_axi_vif` not found in uvm_config_db")
    m_lsu_axi_cfg.protocol      = OCAH_AXI_PROTO_AXI4;
    m_lsu_axi_cfg.addr_width    = SepLsuAddrWidth;
    m_lsu_axi_cfg.data_width    = SepLsuDataWidth;
    m_lsu_axi_cfg.id_width      = SepLsuIdWidth;
    m_lsu_axi_cfg.name_tag      = "sep_lsu_axi";
    m_lsu_axi_cfg.en_ref_model  = 1'b0;
    m_lsu_axi_cfg.en_scoreboard = 1'b0;
    uvm_config_db#(ocah_axi_config)::set(this, "m_lsu_axi_env*", "cfg", m_lsu_axi_cfg);
    m_lsu_axi_env = ocah_axi_env::type_id::create("m_lsu_axi_env", this);
  endfunction

endclass : sep_env
