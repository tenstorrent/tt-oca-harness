// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment: instantiates the shared ocah_jtag_vip environment
// (the VIP's commercial-overridable unit; active, on the ocah_jtag_if
// published by tb_top), the DTP TAP FSM checker subscribed to the VIP env's
// event stream, and owns the DTP-local dtp_tb_if for sequences (reset
// sequencing) and the checker (TAP-state observable).
//
// Downstream STAP TAPs (issue #1056): one shared ocah_jtag_vip slave agent
// per STAP host port, on the ocah_jtag_if tb_top wires from the port's
// forwarded tck/tms/trst_n and TDO. Always built and running; a port's
// device reaches the DUT only while the test sets dtp_tb_if.stap_<x>_ds_en
// (default 0 keeps the wire loopback). The device map is the parity contract
// with the cocotb env/dtp_stap_ds_agent.py: IR width 5, IDCODE at 0x01, one
// writable DS_TDR at 0x02, and a per-port IDCODE and DS_TDR width so a
// swapped or misaligned splice is caught by the chain readback.

class dtp_env extends uvm_env;
  `uvm_component_utils(dtp_env)

  localparam int unsigned StapDsCount = 4;
  localparam int unsigned StapDsIrWidth = 5;
  localparam bit [63:0] StapDsTdrOpcode = 64'h2;

  // Index order is the STAP chain order (TDI to TDO): io, smc, sep, extra0.
  static function string stap_ds_name(int unsigned idx);
    case (idx)
      0:       return "io";
      1:       return "smc";
      2:       return "sep";
      default: return "extra0";
    endcase
  endfunction

  static function bit [31:0] stap_ds_idcode(int unsigned idx);
    case (idx)
      0:       return 32'h1D51_0101;
      1:       return 32'h1D51_0203;
      2:       return 32'h1D51_0305;
      default: return 32'h1D51_0407;
    endcase
  endfunction

  static function int unsigned stap_ds_tdr_width(int unsigned idx);
    case (idx)
      0:       return 12;
      1:       return 16;
      2:       return 20;
      default: return 8;
    endcase
  endfunction

  ocah_jtag_master_config          m_jtag_cfg;
  ocah_jtag_master_env          m_jtag_env;
  dtp_tap_fsm_checker    m_fsm_checker;

  // Shared JTAG named-evidence checker + scan reconstruction.
  // Always built: the FSM checker's aggregate CHK-TAP-STATE lands on every
  // test; required-ID/zero-check rejection is armed only by JTAG-contract
  // tests via jtag_require_checks.
  ocah_jtag_checker      m_jtag_checker;
  ocah_jtag_scan_builder m_scan_builder;
  bit                    jtag_require_checks;

  // Passive shared-VIP AXI observation: one cfg+env per
  // observed JTAG2AXI port. Always built (compile/runtime coverage on every
  // test); zero-check rejection is armed only by AXI-traffic tests via
  // cfg.require_checks.
  ocah_axi_config m_smc_otp_axi_cfg;
  ocah_axi_env m_smc_otp_axi_env;
  ocah_axi_config m_sep_otp_axi_cfg;
  ocah_axi_env m_sep_otp_axi_env;
  ocah_axi_config m_smc_axi_cfg;
  ocah_axi_env m_smc_axi_env;
  ocah_axi_config m_xtrig_axi_cfg;
  ocah_axi_env m_xtrig_axi_env;

  // Active shared-VIP AXI master: the initiator driving the XTRIG CSR
  // AXI-Lite port (XTRIG sequences issue CSR traffic through the env's
  // m_sequencer via ocah_axi_master_sequence).
  ocah_axi_master_config m_xtrig_master_cfg;
  ocah_axi_master_env    m_xtrig_master_env;

  // Active shared-VIP slave agents: the memory-backed responders answering
  // the SMC/SEP OTP AXI-Lite ports and the SMC fabric AXI4 port (sequences
  // program error injection, backdoor memory, and bounded READY
  // backpressure via each agent's seq).
  ocah_axi_slave_config m_smc_otp_slave_cfg;
  ocah_axi_slave_agent  m_smc_otp_slave_agent;
  ocah_axi_slave_config m_sep_otp_slave_cfg;
  ocah_axi_slave_agent  m_sep_otp_slave_agent;
  ocah_axi_slave_config m_smc_axi_slave_cfg;
  ocah_axi_slave_agent  m_smc_axi_slave_agent;

  // Downstream STAP TAP devices, indexed per stap_ds_name().
  ocah_jtag_slave_config m_stap_ds_cfg[StapDsCount];
  ocah_jtag_slave_agent  m_stap_ds_agent[StapDsCount];

  virtual dtp_tb_if tb_vif;

  function new(string name = "dtp_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual dtp_tb_if)::get(this, "", "tb_vif", tb_vif))
      `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not found in uvm_config_db")

    m_jtag_cfg = ocah_jtag_master_config::type_id::create("m_jtag_cfg");
    if (!uvm_config_db#(virtual ocah_jtag_if)::get(this, "", "jtag_vif", m_jtag_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not found in uvm_config_db")
    m_jtag_cfg.is_active       = UVM_ACTIVE;
    m_jtag_cfg.en_monitor      = 1'b1;   // DTP checking rides the OCAH event stream
    m_jtag_cfg.tck_half_period = 50ns;   // 10 MHz TCK
    uvm_config_db#(ocah_jtag_master_config)::set(this, "m_jtag_env*", "cfg", m_jtag_cfg);

    m_jtag_env    = ocah_jtag_master_env::type_id::create("m_jtag_env", this);
    m_fsm_checker = dtp_tap_fsm_checker::type_id::create("m_fsm_checker", this);
    m_fsm_checker.tb_vif = tb_vif;

    m_jtag_checker = ocah_jtag_checker::type_id::create("m_jtag_checker");
    m_jtag_checker.name_tag = "dtp_jtag";
    m_fsm_checker.m_evidence = m_jtag_checker;
    m_scan_builder = ocah_jtag_scan_builder::type_id::create("m_scan_builder", this);

    m_smc_otp_axi_cfg = ocah_axi_config::type_id::create("m_smc_otp_axi_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "smc_otp_axil_vif", m_smc_otp_axi_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `smc_otp_axil_vif` not found in uvm_config_db")
    m_smc_otp_axi_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_smc_otp_axi_cfg.addr_width = 32;
    m_smc_otp_axi_cfg.data_width = 32;
    m_smc_otp_axi_cfg.id_width   = 0;
    m_smc_otp_axi_cfg.name_tag   = "dtp_smc_otp_axil";
    uvm_config_db#(ocah_axi_config)::set(this, "m_smc_otp_axi_env*", "cfg", m_smc_otp_axi_cfg);
    m_smc_otp_axi_env = ocah_axi_env::type_id::create("m_smc_otp_axi_env", this);

    m_sep_otp_axi_cfg = ocah_axi_config::type_id::create("m_sep_otp_axi_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "sep_otp_axil_vif", m_sep_otp_axi_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `sep_otp_axil_vif` not found in uvm_config_db")
    m_sep_otp_axi_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_sep_otp_axi_cfg.addr_width = 32;
    m_sep_otp_axi_cfg.data_width = 32;
    m_sep_otp_axi_cfg.id_width   = 0;
    m_sep_otp_axi_cfg.name_tag   = "dtp_sep_otp_axil";
    uvm_config_db#(ocah_axi_config)::set(this, "m_sep_otp_axi_env*", "cfg", m_sep_otp_axi_cfg);
    m_sep_otp_axi_env = ocah_axi_env::type_id::create("m_sep_otp_axi_env", this);

    m_smc_axi_cfg = ocah_axi_config::type_id::create("m_smc_axi_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "m_axi_vif", m_smc_axi_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `m_axi_vif` not found in uvm_config_db")
    m_smc_axi_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    m_smc_axi_cfg.addr_width = 56;
    m_smc_axi_cfg.data_width = 64;
    m_smc_axi_cfg.id_width   = 2;
    m_smc_axi_cfg.name_tag   = "dtp_smc_axi";
    uvm_config_db#(ocah_axi_config)::set(this, "m_smc_axi_env*", "cfg", m_smc_axi_cfg);
    m_smc_axi_env = ocah_axi_env::type_id::create("m_smc_axi_env", this);

    m_xtrig_axi_cfg = ocah_axi_config::type_id::create("m_xtrig_axi_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "xtrig_axil_vif", m_xtrig_axi_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_axi_if `xtrig_axil_vif` not found in uvm_config_db")
    m_xtrig_axi_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_xtrig_axi_cfg.addr_width = 32;
    m_xtrig_axi_cfg.data_width = 32;
    m_xtrig_axi_cfg.id_width   = 0;
    m_xtrig_axi_cfg.name_tag   = "dtp_xtrig_axil";
    // Monitor + coverage only: the memory-shadow ref-model/scoreboard
    // pairing cannot describe the XTRIG CSR block (volatile status
    // reads, reset-cleared selects, DECERR on unmapped decode); CSR
    // read/response checking is owned by the XTRIG sequences' evidence.
    m_xtrig_axi_cfg.en_scoreboard = 1'b0;
    uvm_config_db#(ocah_axi_config)::set(this, "m_xtrig_axi_env*", "cfg", m_xtrig_axi_cfg);
    m_xtrig_axi_env = ocah_axi_env::type_id::create("m_xtrig_axi_env", this);

    m_xtrig_master_cfg = ocah_axi_master_config::type_id::create("m_xtrig_master_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "xtrig_master_vif", m_xtrig_master_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `xtrig_master_vif` not found in uvm_config_db")
    m_xtrig_master_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_xtrig_master_cfg.addr_width = 32;
    m_xtrig_master_cfg.data_width = 32;
    m_xtrig_master_cfg.id_width   = 0;
    m_xtrig_master_cfg.name_tag   = "dtp_xtrig_master";
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_xtrig_master_env*", "cfg",
                                                m_xtrig_master_cfg);
    m_xtrig_master_env = ocah_axi_master_env::type_id::create("m_xtrig_master_env", this);

    m_smc_otp_slave_cfg = ocah_axi_slave_config::type_id::create("m_smc_otp_slave_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "smc_otp_slave_vif", m_smc_otp_slave_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `smc_otp_slave_vif` not found in uvm_config_db")
    m_smc_otp_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_smc_otp_slave_cfg.addr_width = 32;
    m_smc_otp_slave_cfg.data_width = 32;
    m_smc_otp_slave_cfg.id_width   = 0;
    m_smc_otp_slave_cfg.mem_bytes  = 65536;
    m_smc_otp_slave_cfg.name_tag   = "dtp_smc_otp_slave";
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_smc_otp_slave_agent*", "slave_cfg",
                                               m_smc_otp_slave_cfg);
    m_smc_otp_slave_agent =
            ocah_axi_slave_agent::type_id::create("m_smc_otp_slave_agent", this);

    m_sep_otp_slave_cfg = ocah_axi_slave_config::type_id::create("m_sep_otp_slave_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "sep_otp_slave_vif", m_sep_otp_slave_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `sep_otp_slave_vif` not found in uvm_config_db")
    m_sep_otp_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_sep_otp_slave_cfg.addr_width = 32;
    m_sep_otp_slave_cfg.data_width = 32;
    m_sep_otp_slave_cfg.id_width   = 0;
    m_sep_otp_slave_cfg.mem_bytes  = 65536;
    m_sep_otp_slave_cfg.name_tag   = "dtp_sep_otp_slave";
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_sep_otp_slave_agent*", "slave_cfg",
                                               m_sep_otp_slave_cfg);
    m_sep_otp_slave_agent =
            ocah_axi_slave_agent::type_id::create("m_sep_otp_slave_agent", this);

    m_smc_axi_slave_cfg = ocah_axi_slave_config::type_id::create("m_smc_axi_slave_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "smc_axi_slave_vif", m_smc_axi_slave_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `smc_axi_slave_vif` not found in uvm_config_db")
    m_smc_axi_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
    m_smc_axi_slave_cfg.addr_width = 56;
    m_smc_axi_slave_cfg.data_width = 64;
    m_smc_axi_slave_cfg.id_width   = 2;
    m_smc_axi_slave_cfg.mem_bytes  = 65536;
    m_smc_axi_slave_cfg.name_tag   = "dtp_smc_axi_slave";
    uvm_config_db#(ocah_axi_slave_config)::set(this, "m_smc_axi_slave_agent*", "slave_cfg",
                                               m_smc_axi_slave_cfg);
    m_smc_axi_slave_agent = ocah_axi_slave_agent::type_id::create("m_smc_axi_slave_agent", this);

    for (int unsigned i = 0; i < StapDsCount; i++) begin
      string nm = stap_ds_name(i);
      m_stap_ds_cfg[i] = ocah_jtag_slave_config::type_id::create({"m_stap_", nm, "_ds_cfg"});
      if (!uvm_config_db#(virtual ocah_jtag_if)::get(
              this, "", {"stap_", nm, "_ds_vif"}, m_stap_ds_cfg[i].vif
          ))
        `uvm_fatal(get_type_name(), $sformatf(
                   "virtual ocah_jtag_if `stap_%s_ds_vif` not found in uvm_config_db", nm))
      m_stap_ds_cfg[i].is_active     = UVM_ACTIVE;
      // No passive monitor: the composed-chain scans span the whole
      // network, so per-device scan reconstruction carries no
      // checkable width; the evidence is the device's own state and
      // Update-DR history through ocah_jtag_slave_sequence.
      m_stap_ds_cfg[i].en_monitor    = 1'b0;
      m_stap_ds_cfg[i].ir_width      = StapDsIrWidth;
      m_stap_ds_cfg[i].idcode        = stap_ds_idcode(i);
      // The STAP host port has no downstream tdo_oen input.
      m_stap_ds_cfg[i].drive_tdo_oen = 1'b0;
      m_stap_ds_cfg[i].add_reg("DS_TDR", StapDsTdrOpcode, stap_ds_tdr_width(i), 1'b1);
      uvm_config_db#(ocah_jtag_slave_config)::set(this, {"m_stap_", nm, "_ds_agent*"}, "slave_cfg",
                                                  m_stap_ds_cfg[i]);
      m_stap_ds_agent[i] =
          ocah_jtag_slave_agent::type_id::create({"m_stap_", nm, "_ds_agent"}, this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    m_jtag_env.event_ap.connect(m_fsm_checker.analysis_export);
    m_jtag_env.event_ap.connect(m_scan_builder.analysis_export);
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    m_fsm_checker.report_evidence();
    m_jtag_checker.finalize(jtag_require_checks);
  endfunction

endclass : dtp_env
