// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_3dcr_config_hold_test — PTAP 3DCR CONFIG_HOLD preserve/TLR-clear/TRST-clear sub-cases in a
// seeded order
// (looped runner with per-pass family evidence, 16-pass floor).

class dtp_3dcr_config_hold_test extends dtp_base_test;
    `uvm_component_utils(dtp_3dcr_config_hold_test)

    function new(string name = "dtp_3dcr_config_hold_test",
                 uvm_component parent = null);
        super.new(name, parent);
    endfunction

    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        dtp_stap_scan_test_seq seq = dtp_stap_scan_test_seq::type_id::create("seq");
        seq.scenario = "config_hold";
        return seq;
    endfunction

    virtual function string specific_loops_plusarg();
        return "DTP_3DCR_CONFIG_HOLD_TEST_LOOPS";
    endfunction

    virtual function string group_loops_plusarg();
        return "DTP_SCAN_TEST_LOOPS";
    endfunction

endclass : dtp_3dcr_config_hold_test
