// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_tlr_reset_test scenario sequence — TMS-high walk to
// Test-Logic-Reset against the TAP reference model (the SV port of the
// cocotb dtp_jtag_tlr_reset_test_seq):
//   * from four distinct start states (Run-Test/Idle, Shift-IR, Shift-DR,
//     and a seeded Pause-IR/Pause-DR pick) with BYPASS loaded, walk a
//     seeded 5..8 consecutive TMS=1 cycles and prove the TAP lands in
//     Test-Logic-Reset (CHK-TAP-TLR-TMS5);
//   * a DR scan right after TLR (no IR load) must read the
//     device-identification register: TLR re-selects IDCODE over the loaded
//     BYPASS (CHK-TAP-TLR-IDCODE);
//   * CHK-NONVAC rejects a degenerate pass (repeated start states, sub-5
//     walks, or missed IDCODE restores).
// Per-cycle walk legality lives in the env's dtp_tap_fsm_checker (aggregate
// CHK-TAP-STATE armed by the test). +DTP_JTAG_TAP_CHECKER_NEGATIVE arms a
// deliberately WRONG expected IDCODE so the run must FAIL (the same
// convention as dtp_sanity_test_seq), proving the TLR-selects-IDCODE
// evidence path rejects a bad expectation end to end.
//
// The scan-count cross-check is disabled (cocotb ran without the pin-level
// monitor here): both the navigation into the Pause states and the
// TMS-high walk out of the Shift states cross Shift -> Exit1, publishing
// partial scans the sequence cannot count.

class dtp_jtag_tlr_reset_test_seq extends dtp_jtag_base_test_seq;
    `uvm_object_utils(dtp_jtag_tlr_reset_test_seq)

    function new(string name = "dtp_jtag_tlr_reset_test_seq");
        super.new(name);
    endfunction

    task body();
        ocah_jtag_tap_state_e states[4];
        int unsigned ones_counts[$];
        int unsigned min_ones[$];
        int unsigned idcode_ok = 0;
        bit unique_states = 1'b1;
        bit [63:0] observed;
        bit [31:0] expected_idcode = DtpDefaultIdcode;
        string required[$];

        seed_scenario_rng();
        scan_builder = null;
        required = {"CHK-TAP-RESET-TLR", "CHK-TAP-TLR-TMS5", "CHK-TAP-TLR-IDCODE",
                    "CHK-NONVAC"};
        attach_family_checker(required);

        if (test_cfg.tap_checker_negative) begin
            expected_idcode ^= 32'h2;
            `uvm_warning(get_type_name(), $sformatf(
                "NEGATIVE VALIDATION: arming wrong expected IDCODE 0x%08h instead of 0x%08h",
                expected_idcode, DtpDefaultIdcode))
        end

        states[0] = OCAH_JTAG_RUN_TEST_IDLE;
        states[1] = OCAH_JTAG_SHIFT_IR;
        states[2] = OCAH_JTAG_SHIFT_DR;
        states[3] = $urandom_range(1) ? OCAH_JTAG_PAUSE_IR : OCAH_JTAG_PAUSE_DR;

        foreach (states[s]) begin
            int unsigned ones = $urandom_range(8, 5);
            `uvm_info(get_type_name(), $sformatf(
                "TLR pass %0d/4: start=%s tms_ones=%0d",
                s + 1, states[s].name(), ones), UVM_LOW)

            reset_to_tlr();
            load_ir(BYPASS_INSTR);
            goto_state(states[s]);
            check_state(tap_state_e'(16'h1 << int'(states[s])), "jtag_tlr_chk",
                        $sformatf("start state %s before TMS-high walk",
                                  states[s].name()));

            repeat (ones)
                step(1'b1);
            ones_counts.push_back(ones);
            if (m_family != null)
                void'(m_family.check_tms_ones_to_tlr(ones, tb_vif.tap_state,
                    $sformatf("from=%s", states[s].name())));
            check_state(TEST_LOGIC_RESET, "jtag_tlr_chk",
                        $sformatf("after %0d TMS=1 cycles from %s",
                                  ones, states[s].name()));

            // TLR must re-select the device-identification register over the
            // loaded BYPASS: DR scan with no IR load reads IDCODE.
            step(1'b0);  // TLR -> RTI: scan legs start from Run-Test/Idle
            shift_dr(64'h0, 32, observed);
            family_check("CHK-TAP-TLR-IDCODE", "DR scan after TLR, no IR load",
                         observed[31:0], expected_idcode,
                         $sformatf("from=%s tms_ones=%0d", states[s].name(), ones));
            if (observed[31:0] == DtpDefaultIdcode)
                idcode_ok++;
        end

        foreach (states[i])
            for (int unsigned j = i + 1; j < 4; j++)
                if (states[i] == states[j])
                    unique_states = 1'b0;
        min_ones = ones_counts.min();
        if (m_family != null)
            void'(m_family.expect_true("CHK-NONVAC",
                unique_states && (min_ones[0] >= 5) && (idcode_ok == 4),
                $sformatf("unique_start_states=%0d min_tms_ones=%0d idcode_restored=%0d/4",
                          unique_states, min_ones[0], idcode_ok)));
        finalize_family_checker();
    endtask

endclass : dtp_jtag_tlr_reset_test_seq
