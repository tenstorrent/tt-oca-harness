// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM tests (`<DUT>_tests.sv` convention). Tests are non-reusable by
// definition, so they are NOT packaged: this file is `include`d in module
// scope by tb/tb_top.sv under `ifdef DTP_UVM_TB and compiles as part of the
// top. Test classes stay thin — scenario content lives in dtp_seq_lib_pkg
// sequences; shared infrastructure lives in dtp_env_pkg.
//
// Testlist mapping (testlists/uvm.toml): logical item names are framework-
// neutral VPLAN scenario names; `module` carries the class name here and
// drives +UVM_TESTNAME.

`include "uvm_macros.svh"
import dtp_env_pkg::*;
import dtp_seq_lib_pkg::*;

// ---------------------------------------------------------------------
// Base test: environment construction and the pass-banner contract.
// "UVM TEST PASSED" is emitted only from report_phase and only when the
// global UVM_ERROR/UVM_FATAL counts are both zero (uvm-log parser contract);
// never from sequence or scoreboard code mid-run.
// ---------------------------------------------------------------------
class dtp_uvm_base_test extends uvm_test;
    `uvm_component_utils(dtp_uvm_base_test)

    dtp_uvm_env m_env;

    function new(string name = "dtp_uvm_base_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        m_env = dtp_uvm_env::type_id::create("m_env", this);
    endfunction

    function void report_phase(uvm_phase phase);
        uvm_report_server svr = uvm_report_server::get_server();
        super.report_phase(phase);
        if (svr.get_severity_count(UVM_FATAL) == 0 && svr.get_severity_count(UVM_ERROR) == 0)
            `uvm_info(get_type_name(), "UVM TEST PASSED", UVM_NONE)
        else
            `uvm_info(get_type_name(), "UVM TEST FAILED", UVM_NONE)
    endfunction

endclass : dtp_uvm_base_test

// ---------------------------------------------------------------------
// dtp_uvm_sanity_test — VPLAN 0.1 (`--items dtp_sanity_test`): runs
// dtp_sanity_seq on the shared ocah_jtag_vip agent's sequencer, then
// asserts full FSM state/edge closure via the env checker (this scenario's
// closure obligation — the per-cycle legality check is always on).
// ---------------------------------------------------------------------
class dtp_uvm_sanity_test extends dtp_uvm_base_test;
    `uvm_component_utils(dtp_uvm_sanity_test)

    function new(string name = "dtp_uvm_sanity_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    task run_phase(uvm_phase phase);
        dtp_sanity_seq seq;
        phase.raise_objection(this, "dtp_uvm_sanity_test running");
        seq = dtp_sanity_seq::type_id::create("seq");
        seq.tb_vif = m_env.tb_vif;
        seq.start(m_env.m_jtag_env.m_sequencer);
        m_env.m_fsm_checker.check_fsm_closure();
        phase.drop_objection(this, "dtp_uvm_sanity_test done");
    endtask

endclass : dtp_uvm_sanity_test
