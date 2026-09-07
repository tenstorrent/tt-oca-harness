// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Selftest environment: the shared master env drives the shared fault-slave
// agent on the one harness ocah_axi_if (32-bit address/data, 8-bit IDs,
// AXI4 — the cocotb s_axi bundle geometry), with the side-neutral passive
// env observing the same wires. Sequences consume only frozen surfaces:
// m_master_env.m_sequencer, m_slave_agent.seq, m_axi_env.m_checker/cfg.
//
// `en_passive` gates the wire-level observation stack: the ID-mismatch test
// clears it (uvm_config_db bit "en_passive") because a
// corrupted response ID is an orphan completion to a passive observer — the
// corruption evidence rides the env-owned scenario checker instead.

class ocah_axi_vip_env extends uvm_env;
  `uvm_component_utils(ocah_axi_vip_env)

  ocah_axi_master_config m_master_cfg;
  ocah_axi_master_env    m_master_env;
  ocah_axi_slave_config  m_slave_cfg;
  ocah_axi_slave_agent   m_slave_agent;
  ocah_axi_config        m_axi_cfg;
  ocah_axi_env           m_axi_env;

  // Scenario-level named evidence (response-ID observation checks written
  // by the selftest sequences); finalized here. Tests arm require_checks
  // and required_ids.
  ocah_axi_checker m_checker;
  bit require_checks;

  bit en_passive = 1'b1;

  virtual ocah_axi_if axi_vif;

  function new(string name = "ocah_axi_vip_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "axi_vif", axi_vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `axi_vif` not found in uvm_config_db")
    void'(uvm_config_db#(bit)::get(this, "", "en_passive", en_passive));

    m_master_cfg = ocah_axi_master_config::type_id::create("m_master_cfg");
    m_master_cfg.vif        = axi_vif;
    m_master_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    m_master_cfg.addr_width = 32;
    m_master_cfg.data_width = 32;
    m_master_cfg.id_width   = 8;
    m_master_cfg.name_tag   = "ocah_axi_vip_master";
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_master_env*", "cfg", m_master_cfg);
    m_master_env = ocah_axi_master_env::type_id::create("m_master_env", this);

    m_slave_cfg = ocah_axi_slave_config::type_id::create("m_slave_cfg");
    m_slave_cfg.vif        = axi_vif;
    m_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    m_slave_cfg.addr_width = 32;
    m_slave_cfg.data_width = 32;
    m_slave_cfg.id_width   = 8;
    m_slave_cfg.mem_bytes  = 65536;
    m_slave_cfg.name_tag   = "ocah_axi_vip_slave";
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_slave_agent*", "slave_cfg", m_slave_cfg);
    m_slave_agent = ocah_axi_slave_agent::type_id::create("m_slave_agent", this);

    m_axi_cfg = ocah_axi_config::type_id::create("m_axi_cfg");
    m_axi_cfg.vif           = axi_vif;
    m_axi_cfg.protocol      = OCAH_AXI_PROTO_AXI4;
    m_axi_cfg.addr_width    = 32;
    m_axi_cfg.data_width    = 32;
    m_axi_cfg.id_width      = 8;
    m_axi_cfg.name_tag      = "ocah_axi_vip";
    m_axi_cfg.en_monitor    = en_passive;
    m_axi_cfg.en_ref_model  = en_passive;
    m_axi_cfg.en_scoreboard = en_passive;
    uvm_config_db#(ocah_axi_config)::set(this, "m_axi_env*", "cfg", m_axi_cfg);
    m_axi_env = ocah_axi_env::type_id::create("m_axi_env", this);

    m_checker = ocah_axi_checker::type_id::create("m_checker");
    m_checker.name_tag = "ocah_axi_vip_id";
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    m_checker.finalize(require_checks);
  endfunction

endclass : ocah_axi_vip_env
