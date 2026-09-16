// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Selftest environment. On the one harness ocah_axi_if (32-bit address/data,
// 8-bit IDs, AXI4 — the cocotb s_axi bundle geometry) the shared master env
// drives the shared fault-slave agent with the side-neutral passive env
// observing the same wires. Around the struct-port bridge a second master env
// drives mt_master_vif, whose members tb_top packs into the pulp request
// struct, and a second slave agent answers on mt_axi_vif behind the bridge
// with its own passive env observing it. Sequences consume only frozen
// surfaces: m_*master_env.m_sequencer, m_*slave_agent.seq, the passive cfgs,
// and m_checker.
//
// `en_passive` gates every wire-level observation stack, the covergroup
// subscriber included: the ID-mismatch test clears it (uvm_config_db bit
// "en_passive") because a corrupted response ID is an orphan completion to a
// passive observer — the corruption evidence rides the env-owned scenario
// checker instead.

class ocah_axi_vip_env extends uvm_env;
  `uvm_component_utils(ocah_axi_vip_env)

  ocah_axi_master_config m_master_cfg;
  ocah_axi_master_env    m_master_env;
  ocah_axi_slave_config  m_slave_cfg;
  ocah_axi_slave_agent   m_slave_agent;
  ocah_axi_config        m_axi_cfg;
  ocah_axi_env           m_axi_env;

  ocah_axi_master_config m_mt_master_cfg;
  ocah_axi_master_env    m_mt_master_env;
  ocah_axi_slave_config  m_mt_slave_cfg;
  ocah_axi_slave_agent   m_mt_slave_agent;
  ocah_axi_config        m_mt_axi_cfg;
  ocah_axi_env           m_mt_axi_env;

  // Scenario-level named evidence (response-ID observation checks written
  // by the selftest sequences); finalized here. Tests arm require_checks
  // and required_ids.
  ocah_axi_checker m_checker;
  bit require_checks;

  bit en_passive = 1'b1;

  virtual ocah_axi_if axi_vif;
  virtual ocah_axi_if mt_master_vif;
  virtual ocah_axi_if mt_axi_vif;

  function new(string name = "ocah_axi_vip_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "axi_vif", axi_vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `axi_vif` not found in uvm_config_db")
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "mt_master_vif", mt_master_vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `mt_master_vif` not found in uvm_config_db")
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "mt_axi_vif", mt_axi_vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `mt_axi_vif` not found in uvm_config_db")
    void'(uvm_config_db#(bit)::get(this, "", "en_passive", en_passive));

    m_master_cfg = build_master_cfg("m_master_cfg", axi_vif, "ocah_axi_vip_master");
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_master_env*", "cfg", m_master_cfg);
    m_master_env = ocah_axi_master_env::type_id::create("m_master_env", this);

    m_slave_cfg = build_slave_cfg("m_slave_cfg", axi_vif, "ocah_axi_vip_slave");
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_slave_agent*", "slave_cfg", m_slave_cfg);
    m_slave_agent = ocah_axi_slave_agent::type_id::create("m_slave_agent", this);

    m_axi_cfg = build_passive_cfg("m_axi_cfg", axi_vif, "ocah_axi_vip");
    uvm_config_db#(ocah_axi_config)::set(this, "m_axi_env*", "cfg", m_axi_cfg);
    m_axi_env = ocah_axi_env::type_id::create("m_axi_env", this);

    m_mt_master_cfg = build_master_cfg("m_mt_master_cfg", mt_master_vif, "ocah_axi_vip_mt_master");
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_mt_master_env*", "cfg", m_mt_master_cfg);
    m_mt_master_env = ocah_axi_master_env::type_id::create("m_mt_master_env", this);

    m_mt_slave_cfg = build_slave_cfg("m_mt_slave_cfg", mt_axi_vif, "ocah_axi_vip_mt_slave");
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_mt_slave_agent*", "slave_cfg",
                                               m_mt_slave_cfg);
    m_mt_slave_agent = ocah_axi_slave_agent::type_id::create("m_mt_slave_agent", this);

    m_mt_axi_cfg = build_passive_cfg("m_mt_axi_cfg", mt_axi_vif, "ocah_axi_vip_mt");
    uvm_config_db#(ocah_axi_config)::set(this, "m_mt_axi_env*", "cfg", m_mt_axi_cfg);
    m_mt_axi_env = ocah_axi_env::type_id::create("m_mt_axi_env", this);

    m_checker = ocah_axi_checker::type_id::create("m_checker");
    m_checker.name_tag = "ocah_axi_vip_id";
  endfunction

  // Every harness bus carries the same AXI4 geometry: 32-bit address and
  // data, 8-bit IDs.
  protected function ocah_axi_master_config build_master_cfg(string name, virtual ocah_axi_if vif,
                                                             string name_tag);
    ocah_axi_master_config cfg = ocah_axi_master_config::type_id::create(name);
    cfg.vif        = vif;
    cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    cfg.addr_width = 32;
    cfg.data_width = 32;
    cfg.id_width   = 8;
    cfg.name_tag   = name_tag;
    return cfg;
  endfunction

  protected function ocah_axi_slave_config build_slave_cfg(string name, virtual ocah_axi_if vif,
                                                           string name_tag);
    ocah_axi_slave_config cfg = ocah_axi_slave_config::type_id::create(name);
    cfg.vif        = vif;
    cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    cfg.addr_width = 32;
    cfg.data_width = 32;
    cfg.id_width   = 8;
    cfg.mem_bytes  = 65536;
    cfg.name_tag   = name_tag;
    return cfg;
  endfunction

  protected function ocah_axi_config build_passive_cfg(string name, virtual ocah_axi_if vif,
                                                       string name_tag);
    ocah_axi_config cfg = ocah_axi_config::type_id::create(name);
    cfg.vif           = vif;
    cfg.protocol      = OCAH_AXI_PROTO_AXI4;
    cfg.addr_width    = 32;
    cfg.data_width    = 32;
    cfg.id_width      = 8;
    cfg.name_tag      = name_tag;
    cfg.en_monitor    = en_passive;
    cfg.en_ref_model  = en_passive;
    cfg.en_scoreboard = en_passive;
    cfg.en_cov        = en_passive;
    return cfg;
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    m_checker.finalize(require_checks);
  endfunction

endclass : ocah_axi_vip_env
