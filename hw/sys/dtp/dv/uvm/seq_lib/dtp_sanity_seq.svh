// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP sanity scenario sequence, carrying the full DTP_VPLAN.adoc section 0.1
// semantics on the shared ocah_jtag_vip agent:
//   * deterministic 32-edge TAP FSM closure walk (16 states x tms in {0,1});
//     the env's dtp_tap_fsm_checker model-checks every TCK cycle, and the
//     test asserts full closure via check_fsm_closure() after this sequence
//     completes. Randomized TMS walks run IN ADDITION as stress stimulus,
//     not as the closure mechanism, so pass/fail is seed-independent;
//   * BYPASS (6-bit IR 0x00) 1-TCK TDI-to-TDO latency, fixed + random
//     patterns (checked here from the DR_SCAN item responses);
//   * clean scan-path returns to Run-Test/Idle, final Test-Logic-Reset via
//     five consecutive TMS=1 cycles.

class dtp_sanity_seq extends dtp_jtag_base_seq;
    `uvm_object_utils(dtp_sanity_seq)

    localparam int unsigned RandWalks = 2;
    localparam int unsigned RandWalkSteps = 64;

    function new(string name = "dtp_sanity_seq");
        super.new(name);
    endfunction

    // -----------------------------------------------------------------
    // Deterministic directed walk covering all 32 legal edges by
    // construction, issued as ONE raw item; the checker model-checks every
    // step and the test independently asserts closure afterwards. Starts
    // and ends in Test-Logic-Reset; the last five steps are consecutive
    // TMS=1 cycles.
    // -----------------------------------------------------------------
    task run_deterministic_walk();
        bit walk[] = '{
            // TLR self-loop, RTI, full DR leg incl. pause/exit2 re-shift
            1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0,
            1'b1, 1'b0, 1'b1, 1'b1, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0, 1'b1,
            // full IR leg incl. pause/exit2 re-shift, Select-IR -> TLR
            1'b1, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b1,
            1'b1, 1'b1, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0, 1'b1, 1'b1, 1'b1,
            // Exit2-DR -> Update-DR edge
            1'b0, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b1, 1'b1,
            // Exit2-IR -> Update-IR edge
            1'b1, 1'b1, 1'b0, 1'b0, 1'b1, 1'b0, 1'b1, 1'b1,
            // back to TLR via five consecutive TMS=1 cycles
            1'b0, 1'b1, 1'b1, 1'b1, 1'b1, 1'b1
        };
        bit tdi[];
        tdi = new[walk.size()];
        `uvm_info(get_type_name(), $sformatf(
            "deterministic FSM walk: %0d TMS steps for 32-edge closure", walk.size()), UVM_LOW)
        raw_walk(walk, tdi);
        check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after deterministic walk");
    endtask

    // Randomized raw-TMS stress walks (reproducible via +ntb_random_seed;
    // every choice logged, every step model-checked by the env checker).
    task run_random_walks();
        for (int unsigned w = 0; w < RandWalks; w++) begin
            bit [RandWalkSteps-1:0] tms_bits, tdi_bits;
            bit tms[], tdi[];
            if (!std::randomize(tms_bits, tdi_bits))
                `uvm_fatal(get_type_name(), "randomize() failed for TMS stress walk")
            `uvm_info(get_type_name(), $sformatf(
                "random TMS stress walk %0d/%0d: tms=0x%016h tdi=0x%016h",
                w + 1, RandWalks, tms_bits, tdi_bits), UVM_LOW)
            tms = new[RandWalkSteps];
            tdi = new[RandWalkSteps];
            for (int unsigned i = 0; i < RandWalkSteps; i++) begin
                tms[i] = tms_bits[i];
                tdi[i] = tdi_bits[i];
            end
            raw_walk(tms, tdi);
            goto_tlr_via_tms();
        end
    endtask

    task body();
        bit [63:0] rand_pattern;
        int unsigned seed_val;

        // Start-of-test banner: intent, seed, and randomized configuration.
        if (!$value$plusargs("ntb_random_seed=%d", seed_val)) seed_val = 0;
        `uvm_info(get_type_name(), $sformatf(
            {"DTP SV-UVM sanity (VPLAN 0.1): FSM 32-edge closure + BYPASS 1-TCK ",
             "latency + scan path; seed=%0d (+ntb_random_seed) rand_walks=%0dx%0d steps"},
            seed_val, RandWalks, RandWalkSteps), UVM_LOW)

        // Power-on/system reset sequencing, then TAP reset (VPLAN 0.1 step 1).
        sys_reset();
        tap_reset();

        // sanity_fsm_visit_chk: deterministic 32-edge closure walk.
        run_deterministic_walk();

        // sanity_bypass_latency_chk: BYPASS via 6-bit IR 0x00, fixed + random patterns.
        step(1'b0);  // TLR -> RTI
        load_ir(BYPASS_ALT_INSTR);
        check_bypass_latency(64'hA5A5_5A5A_C3C3_3C3C, 64);
        for (int unsigned p = 0; p < 2; p++) begin
            if (!std::randomize(rand_pattern))
                `uvm_fatal(get_type_name(), "randomize() failed for BYPASS pattern")
            check_bypass_latency(rand_pattern, 64);
        end

        // Randomized raw-TMS stress on top of the deterministic closure.
        run_random_walks();

        // sanity_scan_path_chk epilogue: TLR via five TMS=1 cycles. Full
        // FSM closure is asserted by the test via env.m_fsm_checker after
        // this sequence returns.
        goto_tlr_via_tms();
    endtask

endclass : dtp_sanity_seq
