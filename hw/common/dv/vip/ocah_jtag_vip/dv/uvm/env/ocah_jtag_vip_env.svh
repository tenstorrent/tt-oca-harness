// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Selftest environment. On the one harness ocah_jtag_if the shared master env
// drives the shared reactive TAP device (IDCODE 0x1B34_C0D1, a writable 16-bit
// CTRL register, a read-only 8-bit STATUS register behind a 5-bit instruction
// register). The master monitor's event stream feeds a scan builder for the
// length evidence and the master env's coverage subscriber, which also takes
// the builder's scans; one env-owned ocah_jtag_checker collects every CHK-*
// record; tests arm require_checks and required_ids. Sequences consume only
// frozen surfaces: m_master_env.m_sequencer, m_slave_seq, m_scan_builder, and
// m_checker.
//
// The cocotb twin is dv/cocotb/ocah_jtag_vip_harness.py.

class ocah_jtag_vip_env extends uvm_env;
  `uvm_component_utils(ocah_jtag_vip_env)

  ocah_jtag_master_config  m_master_cfg;
  ocah_jtag_master_env     m_master_env;
  ocah_jtag_slave_config   m_slave_cfg;
  ocah_jtag_slave_agent    m_slave_agent;
  ocah_jtag_slave_sequence m_slave_seq;
  ocah_jtag_scan_builder   m_scan_builder;
  ocah_jtag_checker        m_checker;
  bit require_checks;

  virtual ocah_jtag_if jtag_vif;

  localparam int unsigned IrWidth = 5;
  localparam bit [31:0] Idcode = 32'h1B34_C0D1;
  localparam bit [63:0] IdcodeOpcode = 64'h1;
  localparam bit [63:0] CtrlOpcode = 64'h2;
  localparam bit [63:0] StatusOpcode = 64'h3;

  function new(string name = "ocah_jtag_vip_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual ocah_jtag_if)::get(this, "", "jtag_vif", jtag_vif))
      `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not found in uvm_config_db")

    m_master_cfg = ocah_jtag_master_config::type_id::create("m_master_cfg");
    m_master_cfg.vif             = jtag_vif;
    m_master_cfg.is_active       = UVM_ACTIVE;
    m_master_cfg.en_monitor      = 1'b1;
    m_master_cfg.en_cov          = 1'b1;
    m_master_cfg.tck_half_period = 10ns;
    uvm_config_db#(ocah_jtag_master_config)::set(this, "m_master_env*", "cfg", m_master_cfg);
    m_master_env = ocah_jtag_master_env::type_id::create("m_master_env", this);

    m_slave_cfg = ocah_jtag_slave_config::type_id::create("m_slave_cfg");
    m_slave_cfg.vif           = jtag_vif;
    m_slave_cfg.is_active     = UVM_ACTIVE;
    m_slave_cfg.en_monitor    = 1'b0;
    m_slave_cfg.ir_width      = IrWidth;
    m_slave_cfg.idcode        = Idcode;
    m_slave_cfg.idcode_opcode = IdcodeOpcode;
    m_slave_cfg.add_reg("CTRL", CtrlOpcode, 16, 1'b1);
    m_slave_cfg.add_reg("STATUS", StatusOpcode, 8, 1'b0);
    uvm_config_db#(ocah_jtag_slave_config)::set(this, "m_slave_agent*", "slave_cfg", m_slave_cfg);
    m_slave_agent = ocah_jtag_slave_agent::type_id::create("m_slave_agent", this);

    m_scan_builder = ocah_jtag_scan_builder::type_id::create("m_scan_builder", this);
    m_checker = ocah_jtag_checker::type_id::create("m_checker");
    m_checker.name_tag = "ocah_jtag_vip";
    m_slave_seq = ocah_jtag_slave_sequence::type_id::create("m_slave_seq");
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    m_master_env.event_ap.connect(m_scan_builder.analysis_export);
    if (m_master_env.m_cov != null) m_scan_builder.scan_ap.connect(m_master_env.m_cov.scan_export);
    m_slave_seq.responder = m_slave_agent.m_driver;
    m_slave_seq.evidence  = m_checker;
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    m_checker.finalize(require_checks);
  endfunction
endclass : ocah_jtag_vip_env
