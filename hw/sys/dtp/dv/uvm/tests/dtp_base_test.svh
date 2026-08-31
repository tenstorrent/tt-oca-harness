// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base test: environment construction, the looped-scenario runner, and the
// pass-banner contract. "UVM TEST PASSED" is emitted only from report_phase
// and only when the global UVM_ERROR/UVM_FATAL counts are both zero (uvm-log
// parser contract); never from sequence or scoreboard code mid-run.
//
// Looped-scenario contract (issue #1341, cocotb start_looped_seq parity):
// every looped scenario runs at least MinDefaultLoops passes, each pass with
// its own scenario seed (+ntb_random_seed base + loop index) so directed
// scenarios re-prove back-to-back recovery and randomized scenarios add
// stimulus diversity. Loop counts resolve from plusargs without touching
// test code, mirroring the cocotb environment knobs:
//   +<specific>=N (per test, e.g. +DTP_JTAG_EXTEST_TEST_LOOPS=1)
//   +<group>=N    (per group, e.g. +DTP_BASIC_JTAG_TEST_LOOPS=32)
//   +DTP_TEST_LOOPS=N (suite-wide)
//   +DTP_RANDOM_COUNT=N (random patterns per pass, default 5)
// Looped tests override create_scenario_seq() (+ the plusarg name hooks) and
// inherit run_phase(); tests with bespoke flows override run_phase() as
// before.

class dtp_base_test extends uvm_test;
    `uvm_component_utils(dtp_base_test)

    // Every looped scenario runs at least this many passes by default.
    localparam int unsigned MinDefaultLoops = 16;

    dtp_env m_env;

    function new(string name = "dtp_base_test", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        m_env = dtp_env::type_id::create("m_env", this);
    endfunction

    // ------------------------------------------------------------------
    // Runner-facing knobs (plusargs; the cocotb flow reads the same names
    // as environment variables).
    // ------------------------------------------------------------------

    // Runner-provided seed (+ntb_random_seed, appended by run_dv.py).
    static function int unsigned base_seed();
        int unsigned seed;
        if (!$value$plusargs("ntb_random_seed=%d", seed))
            seed = 1;
        return seed;
    endfunction

    // Random patterns/operations per pass (+DTP_RANDOM_COUNT, default 5).
    static function int unsigned random_count();
        int unsigned count;
        if (!$value$plusargs("DTP_RANDOM_COUNT=%d", count))
            count = 5;
        return count;
    endfunction

    // Loop-count resolution: the specific per-test knob wins, then the group
    // knob, then the suite-wide +DTP_TEST_LOOPS, then the default (floored at
    // MinDefaultLoops). An explicit 0 is a configuration defect.
    function int unsigned loop_count(
        string       specific_plusarg,
        string       group_plusarg,
        int unsigned default_loops = MinDefaultLoops
    );
        int unsigned count;
        string sources[$] = {specific_plusarg, group_plusarg, "DTP_TEST_LOOPS"};
        foreach (sources[i]) begin
            if (sources[i].len() == 0)
                continue;
            if ($value$plusargs({sources[i], "=%d"}, count)) begin
                if (count == 0)
                    `uvm_fatal(get_type_name(), $sformatf(
                        "+%s must be >= 1, got 0", sources[i]))
                return count;
            end
        end
        return (default_loops > MinDefaultLoops) ? default_loops : MinDefaultLoops;
    endfunction

    // ------------------------------------------------------------------
    // Looped-scenario hooks. A looped test overrides create_scenario_seq()
    // and the plusarg name hooks; run_phase() then runs loop_count() passes
    // with per-pass seeds and the standard env handle plumbing.
    // ------------------------------------------------------------------

    // Build one pass's scenario sequence (factory-created, unconfigured).
    virtual function dtp_jtag_base_test_seq create_scenario_seq();
        return null;
    endfunction

    // Per-test and per-group loop-count plusarg names.
    virtual function string specific_loops_plusarg();
        return "";
    endfunction

    virtual function string group_loops_plusarg();
        return "";
    endfunction

    virtual function int unsigned default_loops();
        return MinDefaultLoops;
    endfunction

    // Standard env handle plumbing for every scenario pass; looped tests
    // override to add scenario-specific handles (AXI cfg, slave sequences)
    // and must call super.plumb_scenario_seq().
    virtual function void plumb_scenario_seq(dtp_jtag_base_test_seq seq);
        seq.tb_vif       = m_env.tb_vif;
        seq.jtag_vif     = m_env.m_jtag_cfg.vif;
        seq.evidence     = m_env.m_jtag_checker;
        seq.scan_builder = m_env.m_scan_builder;
    endfunction

    // Clock/reset bring-up (cocotb _bring_up parity): sequence POR and
    // system reset through dtp_tb_if with the startup dbg_disable vector
    // cleared while POR is still asserted, so scenario passes begin with
    // full debug access and assert the disables they gate explicitly.
    task bring_up();
        m_env.tb_vif.dbg_disable <= '0;
        m_env.tb_vif.por_rst_n   <= 1'b0;
        m_env.tb_vif.sys_rst_n   <= 1'b0;
        #200ns;
        m_env.tb_vif.por_rst_n <= 1'b1;
        #100ns;
        m_env.tb_vif.sys_rst_n <= 1'b1;
        #100ns;
    endtask

    task run_looped_scenario();
        int unsigned loops = loop_count(specific_loops_plusarg(),
                                        group_loops_plusarg(), default_loops());
        int unsigned seed   = base_seed();
        int unsigned rcount = random_count();
        bring_up();
        for (int unsigned idx = 0; idx < loops; idx++) begin
            dtp_jtag_base_test_seq seq = create_scenario_seq();
            if (seq == null)
                `uvm_fatal(get_type_name(),
                    "looped test must override create_scenario_seq() (or run_phase())")
            seq.scenario_seed = seed + idx;
            seq.random_count  = rcount;
            seq.loop_index    = idx;
            plumb_scenario_seq(seq);
            `uvm_info(get_type_name(), $sformatf(
                "scenario pass %0d/%0d: %s scenario_seed=%0d random_count=%0d",
                idx + 1, loops, seq.get_type_name(), seq.scenario_seed, rcount),
                UVM_LOW)
            seq.start(m_env.m_jtag_env.m_sequencer);
        end
    endtask

    // Default run flow for looped tests; bespoke tests override run_phase().
    task run_phase(uvm_phase phase);
        phase.raise_objection(this, {get_type_name(), " running"});
        run_looped_scenario();
        phase.drop_objection(this, {get_type_name(), " done"});
    endtask

    function void report_phase(uvm_phase phase);
        uvm_report_server svr = uvm_report_server::get_server();
        super.report_phase(phase);
        if (svr.get_severity_count(UVM_FATAL) == 0 && svr.get_severity_count(UVM_ERROR) == 0)
            `uvm_info(get_type_name(), "UVM TEST PASSED", UVM_NONE)
        else
            `uvm_info(get_type_name(), "UVM TEST FAILED", UVM_NONE)
    endfunction

endclass : dtp_base_test
