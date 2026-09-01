// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base test for the xtrig group: the looped-scenario runner over the XTRIG
// master sequencer. The xtrig scenarios drive the CSR AXI-Lite port through
// the shared VIP master agent and the cross-trigger pins through dtp_tb_if
// — no JTAG traffic at all — so the scenario sequences are
// dtp_xtrig_base_test_seq family (ocah_axi_master_sequence-based) and start
// on env.m_xtrig_master_env.m_sequencer instead of the JTAG sequencer, and
// the TAP FSM checker's zero-cycle activity demand is lifted (any TCK
// activity that does occur is still checked per cycle).
//
// Loop-count and seed resolution is the standard dtp_base_test contract:
// +<specific>=N, +DTP_XTRIG_TEST_LOOPS=N, +DTP_TEST_LOOPS=N, floored at
// MinDefaultLoops, with per-pass scenario seeds (+ntb_random_seed + index)
// and +DTP_RANDOM_COUNT random volume.

class dtp_xtrig_base_test extends dtp_base_test;
    `uvm_component_utils(dtp_xtrig_base_test)

    function new(string name = "dtp_xtrig_base_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        m_env.m_fsm_checker.require_activity = 1'b0;
    endfunction

    // Build one pass's xtrig scenario sequence (factory-created,
    // unconfigured); xtrig tests override this instead of
    // create_scenario_seq().
    virtual function dtp_xtrig_base_test_seq create_xtrig_scenario_seq();
        return null;
    endfunction

    virtual function string group_loops_plusarg();
        return "DTP_XTRIG_TEST_LOOPS";
    endfunction

    // Standard env handle plumbing for every xtrig scenario pass.
    virtual function void plumb_xtrig_scenario_seq(dtp_xtrig_base_test_seq seq);
        seq.tb_vif = m_env.tb_vif;
        seq.cfg    = m_env.m_xtrig_master_cfg;
    endfunction

    task run_xtrig_looped_scenario();
        int unsigned loops = loop_count(specific_loops_plusarg(),
                                        group_loops_plusarg(), default_loops());
        int unsigned seed   = base_seed();
        int unsigned rcount = random_count();
        bring_up();
        for (int unsigned idx = 0; idx < loops; idx++) begin
            dtp_xtrig_base_test_seq seq = create_xtrig_scenario_seq();
            if (seq == null)
                `uvm_fatal(get_type_name(),
                    "xtrig test must override create_xtrig_scenario_seq()")
            seq.scenario_seed = seed + idx;
            seq.random_count  = rcount;
            seq.loop_index    = idx;
            plumb_xtrig_scenario_seq(seq);
            `uvm_info(get_type_name(), $sformatf(
                "scenario pass %0d/%0d: %s scenario=%s scenario_seed=%0d random_count=%0d",
                idx + 1, loops, seq.get_type_name(), seq.scenario,
                seq.scenario_seed, rcount), UVM_LOW)
            seq.start(m_env.m_xtrig_master_env.m_sequencer);
        end
    endtask

    task run_phase(uvm_phase phase);
        phase.raise_objection(this, {get_type_name(), " running"});
        run_xtrig_looped_scenario();
        phase.drop_objection(this, {get_type_name(), " done"});
    endtask

endclass : dtp_xtrig_base_test
