// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC SV-UVM environment: composes, drives nothing, checks no protocol. It
// reads smc_env_cfg and the SMC-local smc_tb_if from uvm_config_db, sets
// the three harness clock periods on the TB interface, fills one shared-VIP
// config per port (interface, geometry, name_tag) and publishes it to that
// agent's subtree, and builds:
//
//   * the active ocah_axi_master_env driving the SEP_IN AXI4 ingress (the
//     VIP's commercial-overridable unit) and the smc_virtual_sequencer that
//     exposes its sequencer to the scenario virtual sequences;
//   * the memory-backed, fault-capable ocah_axi_slave_agent that answers the
//     SYS_OUT AXI4 boundary on the ocah_axi_if tb_top publishes as
//     sys_out_vif; its slave sequence rides the virtual sequencer;
//   * one passive ocah_axi_env on the SEP_IN mirror interface, monitor only:
//     the VIP's memory-shadow reference model cannot describe a CSR block
//     (reset values, read-only fields, side effects), so the bench's own
//     reference models predict on its item stream;
//   * one reference model per scoreboard feature on the SEP_IN stream
//     (smc_scratch_csr_ref_model, smc_default_reg_ref_model,
//     smc_lock_csr_ref_model, smc_mutex_sema_ref_model,
//     smc_spm_mem_ref_model), and the
//     always-on smc_scoreboard pairing each feature's expected stream with
//     the observed one.
//
// The cocotb twin is env/smc_env.py.

class smc_env extends ocah_env;
  `uvm_component_utils(smc_env)

  smc_env_cfg       cfg;
  virtual smc_tb_if tb_vif;

  // SEP_IN initiator: shared VIP master env on the interface tb_top publishes.
  ocah_axi_master_config m_sep_in_master_cfg;
  ocah_axi_master_env    m_sep_in_master_env;

  // SEP_IN observation: shared VIP passive env, monitor only.
  ocah_axi_config m_sep_in_axi_cfg;
  ocah_axi_env    m_sep_in_axi_env;

  // SYS_OUT egress: the shared VIP responder on the ocah_axi_if the struct
  // bridge feeds in tb_top.
  ocah_axi_slave_config m_sys_out_slave_cfg;
  ocah_axi_slave_agent  m_sys_out_slave_agent;

  // Always-on checking: one reference model per feature and the scoreboard
  // that pairs them; the virtual sequencer every pass runs on.
  smc_scratch_csr_ref_model m_scratch_csr_ref_model;
  smc_default_reg_ref_model m_default_reg_ref_model;
  smc_lock_csr_ref_model    m_lock_csr_ref_model;
  smc_mutex_sema_ref_model  m_mutex_sema_ref_model;
  smc_spm_mem_ref_model     m_spm_mem_ref_model;
  smc_scoreboard            m_scoreboard;
  smc_virtual_sequencer     m_vseqr;

  function new(string name = "smc_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (!uvm_config_db#(virtual smc_tb_if)::get(this, "", "tb_vif", tb_vif))
      `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not found in uvm_config_db")
    tb_vif.ref_clk_period_ns    = cfg.ref_clk_period_ns;
    tb_vif.smc_clk_period_ns    = cfg.clk_period_ns;
    tb_vif.periph_clk_period_ns = cfg.periph_clk_period_ns;
    `uvm_info(get_type_name(), {"env cfg: ", cfg.convert2string()}, UVM_MEDIUM)

    build_sep_in_master();
    build_sep_in_passive();
    build_sys_out_slave();

    m_scratch_csr_ref_model =
            smc_scratch_csr_ref_model::type_id::create("m_scratch_csr_ref_model", this);
    m_scratch_csr_ref_model.tb_vif = tb_vif;
    m_default_reg_ref_model =
            smc_default_reg_ref_model::type_id::create("m_default_reg_ref_model", this);
    m_default_reg_ref_model.tb_vif = tb_vif;
    m_lock_csr_ref_model =
            smc_lock_csr_ref_model::type_id::create("m_lock_csr_ref_model", this);
    m_lock_csr_ref_model.tb_vif = tb_vif;
    m_mutex_sema_ref_model =
            smc_mutex_sema_ref_model::type_id::create("m_mutex_sema_ref_model", this);
    m_mutex_sema_ref_model.tb_vif = tb_vif;
    m_spm_mem_ref_model =
            smc_spm_mem_ref_model::type_id::create("m_spm_mem_ref_model", this);
    m_spm_mem_ref_model.tb_vif = tb_vif;
    m_scoreboard = smc_scoreboard::type_id::create("m_scoreboard", this);

    m_vseqr = smc_virtual_sequencer::type_id::create("m_vseqr", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    m_vseqr.m_sep_in_seqr       = m_sep_in_master_env.m_sequencer;
    m_vseqr.m_sys_out_slave_seq = m_sys_out_slave_agent.seq;
    // scratch_csr: the monitor stream feeds the reference model and the
    // scoreboard's observed side; the model's expected_ap feeds the other.
    m_sep_in_axi_env.item_ap.connect(m_scratch_csr_ref_model.analysis_export);
    m_scratch_csr_ref_model.expected_ap.connect(m_scoreboard.scratch_expected_export);
    m_sep_in_axi_env.item_ap.connect(m_scoreboard.scratch_observed_export);
    // default_reg: the same monitor stream, judged by its own model against
    // the generated post-reset content of the catalogued registers.
    m_sep_in_axi_env.item_ap.connect(m_default_reg_ref_model.analysis_export);
    m_default_reg_ref_model.expected_ap.connect(m_scoreboard.default_reg_expected_export);
    m_sep_in_axi_env.item_ap.connect(m_scoreboard.default_reg_observed_export);
    // lock_csr: woset locks and the registers they mask.
    m_sep_in_axi_env.item_ap.connect(m_lock_csr_ref_model.analysis_export);
    m_lock_csr_ref_model.expected_ap.connect(m_scoreboard.lock_expected_export);
    m_sep_in_axi_env.item_ap.connect(m_scoreboard.lock_observed_export);
    // mutex_sema: side-effecting reads and accumulating writes.
    m_sep_in_axi_env.item_ap.connect(m_mutex_sema_ref_model.analysis_export);
    m_mutex_sema_ref_model.expected_ap.connect(m_scoreboard.mutex_expected_export);
    m_sep_in_axi_env.item_ap.connect(m_scoreboard.mutex_observed_export);
    // spm_mem: 64-bit words of the SPM window.
    m_sep_in_axi_env.item_ap.connect(m_spm_mem_ref_model.analysis_export);
    m_spm_mem_ref_model.expected_ap.connect(m_scoreboard.spm_expected_export);
    m_sep_in_axi_env.item_ap.connect(m_scoreboard.spm_observed_export);
  endfunction

  // ------------------------------------------------------------------
  // Composition helpers (build_phase).
  // ------------------------------------------------------------------

  protected function void build_sep_in_master();
    m_sep_in_master_cfg = ocah_axi_master_config::type_id::create("m_sep_in_master_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "sep_in_master_vif", m_sep_in_master_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `sep_in_master_vif` not found in uvm_config_db")
    m_sep_in_master_cfg.protocol       = OCAH_AXI_PROTO_AXI4;
    m_sep_in_master_cfg.addr_width     = SmcSepInAddrWidth;
    m_sep_in_master_cfg.data_width     = SmcSepInDataWidth;
    m_sep_in_master_cfg.id_width       = SmcSepInIdWidth;
    m_sep_in_master_cfg.timeout_cycles = cfg.axi_timeout_cycles;
    m_sep_in_master_cfg.name_tag       = "smc_sep_in_master";
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_sep_in_master_env*", "cfg",
                                                m_sep_in_master_cfg);
    m_sep_in_master_env = ocah_axi_master_env::type_id::create("m_sep_in_master_env", this);
  endfunction

  protected function void build_sep_in_passive();
    m_sep_in_axi_cfg = ocah_axi_config::type_id::create("m_sep_in_axi_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "sep_in_axi_vif", m_sep_in_axi_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `sep_in_axi_vif` not found in uvm_config_db")
    m_sep_in_axi_cfg.protocol      = OCAH_AXI_PROTO_AXI4;
    m_sep_in_axi_cfg.addr_width    = SmcSepInAddrWidth;
    m_sep_in_axi_cfg.data_width    = SmcSepInDataWidth;
    m_sep_in_axi_cfg.id_width      = SmcSepInIdWidth;
    m_sep_in_axi_cfg.name_tag      = "smc_sep_in_axi";
    m_sep_in_axi_cfg.en_ref_model  = 1'b0;
    m_sep_in_axi_cfg.en_scoreboard = 1'b0;
    uvm_config_db#(ocah_axi_config)::set(this, "m_sep_in_axi_env*", "cfg", m_sep_in_axi_cfg);
    m_sep_in_axi_env = ocah_axi_env::type_id::create("m_sep_in_axi_env", this);
  endfunction

  protected function void build_sys_out_slave();
    m_sys_out_slave_cfg = ocah_axi_slave_config::type_id::create("m_sys_out_slave_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "sys_out_vif", m_sys_out_slave_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `sys_out_vif` not found in uvm_config_db")
    m_sys_out_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    m_sys_out_slave_cfg.addr_width = SmcSysOutAddrWidth;
    m_sys_out_slave_cfg.data_width = SmcSysOutDataWidth;
    m_sys_out_slave_cfg.id_width   = SmcSysOutIdWidth;
    m_sys_out_slave_cfg.mem_bytes  = cfg.sys_out_mem_bytes;
    m_sys_out_slave_cfg.name_tag   = "smc_sys_out";
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_sys_out_slave_agent*", "slave_cfg",
                                               m_sys_out_slave_cfg);
    m_sys_out_slave_agent = ocah_axi_slave_agent::type_id::create("m_sys_out_slave_agent", this);
  endfunction

endclass : smc_env
