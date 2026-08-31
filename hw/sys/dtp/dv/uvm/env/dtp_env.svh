// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment: instantiates the shared ocah_jtag_vip environment
// (the VIP's commercial-overridable unit; active, on the ocah_jtag_if
// published by tb_top), the DTP TAP FSM checker subscribed to the VIP env's
// event stream, and owns the DTP-local dtp_tb_if for sequences (reset
// sequencing) and the checker (TAP-state observable).

class dtp_env extends uvm_env;
    `uvm_component_utils(dtp_env)

    ocah_jtag_master_config          m_jtag_cfg;
    ocah_jtag_master_env          m_jtag_env;
    dtp_tap_fsm_checker    m_fsm_checker;

    // Shared JTAG named-evidence checker + scan reconstruction (issue #3296).
    // Always built: the FSM checker's aggregate CHK-TAP-STATE lands on every
    // test; required-ID/zero-check rejection is armed only by JTAG-contract
    // tests via jtag_require_checks.
    ocah_jtag_checker      m_jtag_checker;
    ocah_jtag_scan_builder m_scan_builder;
    bit                    jtag_require_checks;

    // Passive shared-VIP AXI observation (issue #3295): one cfg+env per
    // observed JTAG2AXI port. Always built (compile/runtime coverage on every
    // test); zero-check rejection is armed only by AXI-traffic tests via
    // cfg.require_checks.
    ocah_axi_config m_smc_otp_axi_cfg;
    ocah_axi_env m_smc_otp_axi_env;
    ocah_axi_config m_smc_axi_cfg;
    ocah_axi_env m_smc_axi_env;

    // Active shared-VIP slave agents: the memory-backed responders answering
    // the SMC OTP AXI-Lite port and the SMC fabric AXI4 port (sequences
    // program error injection and backdoor memory via each agent's seq).
    ocah_axi_slave_config m_smc_otp_slave_cfg;
    ocah_axi_slave_agent  m_smc_otp_slave_agent;
    ocah_axi_slave_config m_smc_axi_slave_cfg;
    ocah_axi_slave_agent  m_smc_axi_slave_agent;

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
        if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "smc_otp_axil_vif",
                                                      m_smc_otp_axi_cfg.vif))
            `uvm_fatal(get_type_name(),
                "virtual ocah_axi_if `smc_otp_axil_vif` not found in uvm_config_db")
        m_smc_otp_axi_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
        m_smc_otp_axi_cfg.addr_width = 32;
        m_smc_otp_axi_cfg.data_width = 32;
        m_smc_otp_axi_cfg.id_width   = 0;
        m_smc_otp_axi_cfg.name_tag   = "dtp_smc_otp_axil";
        uvm_config_db#(ocah_axi_config)::set(this, "m_smc_otp_axi_env*", "cfg",
                                          m_smc_otp_axi_cfg);
        m_smc_otp_axi_env = ocah_axi_env::type_id::create("m_smc_otp_axi_env", this);

        m_smc_axi_cfg = ocah_axi_config::type_id::create("m_smc_axi_cfg");
        if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "m_axi_vif",
                                                      m_smc_axi_cfg.vif))
            `uvm_fatal(get_type_name(),
                "virtual ocah_axi_if `m_axi_vif` not found in uvm_config_db")
        m_smc_axi_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
        m_smc_axi_cfg.addr_width = 56;
        m_smc_axi_cfg.data_width = 64;
        m_smc_axi_cfg.id_width   = 2;
        m_smc_axi_cfg.name_tag   = "dtp_smc_axi";
        uvm_config_db#(ocah_axi_config)::set(this, "m_smc_axi_env*", "cfg", m_smc_axi_cfg);
        m_smc_axi_env = ocah_axi_env::type_id::create("m_smc_axi_env", this);

        m_smc_otp_slave_cfg = ocah_axi_slave_config::type_id::create("m_smc_otp_slave_cfg");
        if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "smc_otp_slave_vif",
                                                      m_smc_otp_slave_cfg.vif))
            `uvm_fatal(get_type_name(),
                "virtual ocah_axi_if `smc_otp_slave_vif` not found in uvm_config_db")
        m_smc_otp_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
        m_smc_otp_slave_cfg.addr_width = 32;
        m_smc_otp_slave_cfg.data_width = 32;
        m_smc_otp_slave_cfg.id_width   = 0;
        m_smc_otp_slave_cfg.mem_bytes  = 65536;
        m_smc_otp_slave_cfg.name_tag   = "dtp_smc_otp_slave";
        uvm_config_db#(ocah_axi_slave_config)::set(this, "m_smc_otp_slave_agent*",
                                                   "slave_cfg", m_smc_otp_slave_cfg);
        m_smc_otp_slave_agent =
            ocah_axi_slave_agent::type_id::create("m_smc_otp_slave_agent", this);

        m_smc_axi_slave_cfg = ocah_axi_slave_config::type_id::create("m_smc_axi_slave_cfg");
        if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", "smc_axi_slave_vif",
                                                      m_smc_axi_slave_cfg.vif))
            `uvm_fatal(get_type_name(),
                "virtual ocah_axi_if `smc_axi_slave_vif` not found in uvm_config_db")
        m_smc_axi_slave_cfg.protocol   = OCAH_AXI_PROTO_AXI4;
        m_smc_axi_slave_cfg.addr_width = 56;
        m_smc_axi_slave_cfg.data_width = 64;
        m_smc_axi_slave_cfg.id_width   = 2;
        m_smc_axi_slave_cfg.mem_bytes  = 65536;
        m_smc_axi_slave_cfg.name_tag   = "dtp_smc_axi_slave";
        uvm_config_db#(ocah_axi_slave_config)::set(this, "m_smc_axi_slave_agent*",
                                                   "slave_cfg", m_smc_axi_slave_cfg);
        m_smc_axi_slave_agent =
            ocah_axi_slave_agent::type_id::create("m_smc_axi_slave_agent", this);
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
