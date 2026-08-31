// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base JTAG sequence: extends the VIP-level ocah_jtag_master_sequence (which
// owns the protocol-neutral stimulus API: raw steps/walks, IR/DR scans, TAP
// reset) with the DTP-specific layer (pin-level driving lives in the VIP
// driver; per-cycle FSM legality/closure checking lives in the env's
// dtp_tap_fsm_checker subscriber). This base keeps:
//   * DTP-local reset sequencing (por/sys via dtp_tb_if),
//   * scan-path state checks against the DUT one-hot TAP state
//     (sanity_scan_path_chk — coarse, after-transaction checks),
//   * the BYPASS 1-TCK latency check (sanity_bypass_latency_chk), which
//     compares spec-derived expected TDO with the DR_SCAN item response.

class dtp_jtag_base_test_seq extends ocah_jtag_master_sequence;
    `uvm_object_utils(dtp_jtag_base_test_seq)

    localparam int unsigned IrWidth = 6;
    // DTP primary TAP default device-identification value (bit 0 = marker).
    localparam bit [31:0] DtpDefaultIdcode = 32'h0000_0001;

    // Plumbed by the test from dtp_env before start(sequencer).
    virtual dtp_tb_if tb_vif;

    // Plumbed by the test (env.m_jtag_cfg.vif) for scenarios that hold or
    // sequence TRST directly (reset-family tests). Safe alongside the VIP
    // driver, which drives trst_n only while executing a TAP_RESET item.
    virtual ocah_jtag_if jtag_vif;

    // Optional shared-VIP evidence handles (issue #3296): when plumbed, TAP
    // resets, TLR walks, BYPASS latency, and reconstructed scan lengths also
    // emit named CHK-* evidence through env.m_jtag_checker.
    ocah_jtag_checker      evidence;
    ocah_jtag_scan_builder scan_builder;

    // Looped-scenario contract (issue #1341): the test's looped runner sets
    // scenario_seed = base seed (+ntb_random_seed) + loop index and
    // random_count (+DTP_RANDOM_COUNT) before each start(); body() calls
    // seed_scenario_rng() first so every pass draws a distinct, replayable
    // random stream.
    int unsigned scenario_seed = 0;
    int unsigned random_count  = 5;
    // Pass index within the looped run (0-based); pass 0 follows the test's
    // clock/reset bring-up, later passes re-enter with the DUT live.
    int unsigned loop_index = 0;

    function new(string name = "dtp_jtag_base_test_seq");
        super.new(name);
    endfunction

    // Seed this body() process from the per-pass scenario seed. start()
    // forks body() in its own process, so the seed scopes to this pass.
    function void seed_scenario_rng();
        process p = process::self();
        if (p != null)
            p.srandom(scenario_seed);
    endfunction

    // --- deterministic pattern helpers (cocotb directed_patterns parity) ---
    static function bit [63:0] bit_mask(int unsigned width);
        return (width == 0) ? '0 : (width >= 64) ? '1 : ((64'h1 << width) - 1);
    endfunction

    function bit [63:0] random_pattern(int unsigned width);
        return {$urandom, $urandom} & bit_mask(width);
    endfunction

    // Edge, alternating, walking-one/zero, and seeded random patterns,
    // deduplicated in insertion order (mirrors cocotb directed_patterns).
    function void directed_patterns(int unsigned width, ref bit [63:0] patterns[$]);
        bit [63:0] mask = bit_mask(width);
        bit [63:0] fixed[$];
        int unsigned bit_positions[$];
        bit seen[bit [63:0]];
        patterns.delete();
        fixed.push_back('0);
        fixed.push_back(mask);
        fixed.push_back(64'hAAAA_AAAA_AAAA_AAAA & mask);
        fixed.push_back(64'h5555_5555_5555_5555 & mask);
        fixed.push_back(64'hA5A5_5A5A_C3C3_3C3C & mask);
        fixed.push_back(64'h0123_4567_89AB_CDEF & mask);
        bit_positions = {0, width / 4, width / 2, (3 * width) / 4, width - 1};
        bit_positions.sort();
        foreach (bit_positions[i]) begin
            if (i > 0 && bit_positions[i] == bit_positions[i-1])
                continue;
            fixed.push_back(64'h1 << bit_positions[i]);
            fixed.push_back(mask ^ (64'h1 << bit_positions[i]));
        end
        for (int unsigned r = 0; r < random_count; r++)
            fixed.push_back(random_pattern(width));
        foreach (fixed[i]) begin
            if (!seen.exists(fixed[i])) begin
                seen[fixed[i]] = 1'b1;
                patterns.push_back(fixed[i]);
            end
        end
    endfunction

    // `checker_tag` because bare `checker` is an IEEE 1800 reserved word
    // (VCS tolerates it; Verilator lint does not).
    function void check_state(tap_state_e expected, string checker_tag, string what);
        if (tb_vif.tap_state !== expected)
            `uvm_error(checker_tag, $sformatf(
                "%s: expected TAP state %s (0x%04h), got 0x%04h",
                what, expected.name(), expected, tb_vif.tap_state))
        else
            `uvm_info(checker_tag, $sformatf("%s: TAP state %s as expected", what, expected.name()),
                      UVM_MEDIUM)
    endfunction

    // Power-on/system reset sequencing (DTP-local, via dtp_tb_if). The JTAG
    // pins themselves idle under the VIP driver (tck=0, tms=1, trst_n=1);
    // the TAP's asynchronous reset is exercised by tap_reset() right after.
    task sys_reset();
        `uvm_info(get_type_name(), "sequencing power-on and system resets", UVM_MEDIUM)
        tb_vif.por_rst_n <= 1'b0;
        tb_vif.sys_rst_n <= 1'b0;
        #200ns;
        tb_vif.por_rst_n <= 1'b1;
        #100ns;
        tb_vif.sys_rst_n <= 1'b1;
        #100ns;
    endtask

    // TAP reset: TRST pulse via the driver -> Test-Logic-Reset.
    task tap_reset();
        `uvm_info(get_type_name(), "asserting TRST for TAP reset", UVM_MEDIUM)
        tap_reset_op();
        if (evidence != null)
            void'(evidence.check_reset_to_tlr(tb_vif.tap_state, "after TRST release"));
        check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after TRST release");
    endtask

    // Return to Test-Logic-Reset from any state via five TMS=1 cycles.
    task goto_tlr_via_tms();
        bit tms[] = '{1'b1, 1'b1, 1'b1, 1'b1, 1'b1};
        bit tdi[] = '{1'b0, 1'b0, 1'b0, 1'b0, 1'b0};
        raw_walk(tms, tdi);
        if (evidence != null)
            void'(evidence.check_tms_ones_to_tlr(5, tb_vif.tap_state, "after 5x TMS=1"));
        check_state(TEST_LOGIC_RESET, "sanity_scan_path_chk", "after 5x TMS=1");
    endtask

    // Hold or release TRST directly (active-low), stepping TCK with TMS=1 so
    // the env's per-cycle FSM checker prediction (TLR self-loop) stays valid
    // while the asynchronous reset dominates. Mirrors the cocotb driver-level
    // SET_TRST op used by the reset-family scenarios.
    task set_trst(bit value, int unsigned cycles = 1);
        if (jtag_vif == null)
            `uvm_fatal(get_type_name(), "set_trst() needs jtag_vif plumbed by the test")
        jtag_vif.trst_n <= value;
        repeat (cycles > 0 ? cycles : 1)
            step(1'b1);
        if (value == 1'b0) begin
            sync_model(OCAH_JTAG_TEST_LOGIC_RESET);
            if (evidence != null)
                evidence.reset_model();
        end
    endtask

    // Pulse power-on reset while TCK keeps stepping with TMS=1 (the TAP's
    // POR independence contract is checked by the caller from tb_vif state).
    task pulse_por(int unsigned cycles = 5);
        tb_vif.por_rst_n <= 1'b0;
        repeat (cycles > 0 ? cycles : 1)
            step(1'b1);
        tb_vif.por_rst_n <= 1'b1;
        #100ns;
    endtask

    // IR scan from Run-Test/Idle (LSB-first), back to Run-Test/Idle.
    virtual task load_ir(bit [IrWidth-1:0] instr);
        bit [63:0] captured;
        `uvm_info(get_type_name(), $sformatf("IR scan: loading 0x%02h (%0d bits)", instr, IrWidth),
                  UVM_MEDIUM)
        ir_scan(64'(instr), IrWidth, captured);
        check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after IR scan");
        check_last_scan_length(1'b1, IrWidth, $sformatf("ir=0x%02h", instr));
    endtask

    // DR scan from Run-Test/Idle (LSB-first), returning observed TDO.
    virtual task shift_dr(input bit [63:0] pattern, input int unsigned width,
                          output bit [63:0] observed);
        dr_scan(pattern, width, observed);
        check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after DR scan");
        check_last_scan_length(1'b0, width, $sformatf("pattern=0x%0h", pattern));
    endtask

    // CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN: the newest reconstructed scan of
    // this kind (published on the Shift->Exit1 edge, cycles before the
    // driver's back-to-RTI leg completes) must span exactly the driven width.
    function void check_last_scan_length(bit is_ir, int unsigned width, string context_s);
        ocah_jtag_scan_item item;
        if (evidence == null || scan_builder == null)
            return;
        if (is_ir ? scan_builder.ir_items.size() == 0 : scan_builder.dr_items.size() == 0) begin
            `uvm_error("sanity_scan_len_chk", $sformatf(
                "no reconstructed %s scan observed (%s)", is_ir ? "IR" : "DR", context_s))
            return;
        end
        item = is_ir ? scan_builder.ir_items[$] : scan_builder.dr_items[$];
        void'(evidence.check_scan_length(item, width, context_s));
    endfunction

    // Read the 32-bit device-identification register via IDCODE.
    task read_idcode(output bit [63:0] observed);
        load_ir(IDCODE_INSTR);
        shift_dr(64'h0, 32, observed);
    endtask

    // sanity_bypass_latency_chk: BYPASS (IR 0x00) => exactly 1-TCK
    // TDI-to-TDO delay: observed = {pattern[width-2:0], 1'b0} LSB-first.
    task check_bypass_latency(bit [63:0] pattern, int unsigned width);
        bit [63:0] observed, expected;
        expected = ocah_jtag_checker::predict_bypass_tdo(pattern, width);
        shift_dr(pattern, width, observed);
        if (evidence != null) begin
            void'(evidence.check_bypass_latency(observed, pattern, width));
        end
        else if (observed !== expected)
            `uvm_error("sanity_bypass_latency_chk", $sformatf(
                "BYPASS TDI-to-TDO latency not 1 TCK: pattern=0x%016h width=%0d expected=0x%016h observed=0x%016h",
                pattern, width, expected, observed))
        else
            `uvm_info("sanity_bypass_latency_chk", $sformatf(
                "BYPASS 1-TCK latency OK: pattern=0x%016h width=%0d observed=0x%016h",
                pattern, width, observed), UVM_MEDIUM)
    endtask

endclass : dtp_jtag_base_test_seq
