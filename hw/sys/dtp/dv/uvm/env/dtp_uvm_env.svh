// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment: instantiates the shared ocah_jtag_vip environment
// (the VIP's commercial-overridable unit; active, on the ocah_jtag_if
// published by tb_top), the DTP TAP FSM checker subscribed to the VIP env's
// event stream, and owns the DTP-local dtp_tb_if for sequences (reset
// sequencing) and the checker (TAP-state observable).

class dtp_uvm_env extends uvm_env;
    `uvm_component_utils(dtp_uvm_env)

    ocah_jtag_cfg       m_jtag_cfg;
    ocah_jtag_env       m_jtag_env;
    dtp_tap_fsm_checker m_fsm_checker;

    virtual dtp_tb_if tb_vif;

    function new(string name = "dtp_uvm_env", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if (!uvm_config_db#(virtual dtp_tb_if)::get(this, "", "tb_vif", tb_vif))
            `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not found in uvm_config_db")

        m_jtag_cfg = ocah_jtag_cfg::type_id::create("m_jtag_cfg");
        if (!uvm_config_db#(virtual ocah_jtag_if)::get(this, "", "jtag_vif", m_jtag_cfg.vif))
            `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not found in uvm_config_db")
        m_jtag_cfg.is_active       = UVM_ACTIVE;
        m_jtag_cfg.en_monitor      = 1'b1;   // DTP checking rides the OCAH event stream
        m_jtag_cfg.tck_half_period = 50ns;   // 10 MHz TCK
        uvm_config_db#(ocah_jtag_cfg)::set(this, "m_jtag_env*", "cfg", m_jtag_cfg);

        m_jtag_env    = ocah_jtag_env::type_id::create("m_jtag_env", this);
        m_fsm_checker = dtp_tap_fsm_checker::type_id::create("m_fsm_checker", this);
        m_fsm_checker.tb_vif = tb_vif;
    endfunction

    function void connect_phase(uvm_phase phase);
        super.connect_phase(phase);
        m_jtag_env.event_ap.connect(m_fsm_checker.analysis_export);
    endfunction

endclass : dtp_uvm_env
