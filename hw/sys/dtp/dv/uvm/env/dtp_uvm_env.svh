// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment: owns the virtual interfaces published by tb_top
// (shared ocah_jtag_if pins + DTP-local dtp_tb_if resets/observables) and
// hands them to sequences via the test. Agents and scoreboards attach here
// when the ocah_jtag_vip SV-UVM agent lands.

class dtp_uvm_env extends uvm_env;
    `uvm_component_utils(dtp_uvm_env)

    virtual ocah_jtag_if jtag_vif;
    virtual dtp_tb_if    tb_vif;

    function new(string name = "dtp_uvm_env", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if (!uvm_config_db#(virtual ocah_jtag_if)::get(this, "", "jtag_vif", jtag_vif))
            `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not found in uvm_config_db")
        if (!uvm_config_db#(virtual dtp_tb_if)::get(this, "", "tb_vif", tb_vif))
            `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not found in uvm_config_db")
    endfunction

endclass : dtp_uvm_env
