// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_undef_instr_test — Basic JTAG VPLAN scenario: every
// reserved/undefined IR opcode falls back to the one-bit BYPASS path, run
// through the looped-scenario floor with per-pass seeds.

class dtp_jtag_undef_instr_test extends dtp_base_test;
    `uvm_component_utils(dtp_jtag_undef_instr_test)

    function new(string name = "dtp_jtag_undef_instr_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        return dtp_jtag_undef_instr_test_seq::type_id::create("seq");
    endfunction

    virtual function string specific_loops_plusarg();
        return "DTP_JTAG_UNDEF_INSTR_TEST_LOOPS";
    endfunction

    virtual function string group_loops_plusarg();
        return "DTP_BASIC_JTAG_TEST_LOOPS";
    endfunction

endclass : dtp_jtag_undef_instr_test
