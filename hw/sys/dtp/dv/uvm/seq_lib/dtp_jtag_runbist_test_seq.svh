// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_runbist_test scenario sequence: RUNBIST instruction decode
// (CHK-IR-DECODE) and scan-path response checks. The OSS DTP top loops the
// RUNBIST register path, so directed + seeded random 8-bit scans must
// produce distinct, nonzero responses (CHK-RUNBIST-RESPONSE) — a stuck or
// tied-off path cannot satisfy both.

class dtp_jtag_runbist_test_seq extends dtp_jtag_cmd_lib_seq;
    `uvm_object_utils(dtp_jtag_runbist_test_seq)

    function new(string name = "dtp_jtag_runbist_test_seq");
        super.new(name);
    endfunction

    task body();
        bit [63:0] patterns[$];
        bit [7:0]  results[$];
        bit        seen_results[bit [7:0]];
        bit [63:0] observed;
        bit        any_nonzero = 1'b0;
        string     results_s = "";

        seed_scenario_rng();
        attach_family_checker({"CHK-TAP-RESET-TLR", "CHK-IR-DECODE",
                               "CHK-RUNBIST-RESPONSE", "CHK-SCAN-COUNT",
                               "CHK-SCAN-IR-LEN", "CHK-SCAN-DR-LEN",
                               "CHK-NONVAC"});
        reset_to_tlr();
        load_ir(RUNBIST_INSTR);
        expect_decoded_instruction(RUNBIST_INSTR);

        patterns = {64'h00, 64'hFF, 64'h5A, 64'hA5};
        for (int unsigned r = 0; r < random_count; r++)
            patterns.push_back(random_pattern(8));

        foreach (patterns[p]) begin
            shift_dr(patterns[p], 8, observed);
            results.push_back(observed[7:0]);
            seen_results[observed[7:0]] = 1'b1;
            if (observed[7:0] != 8'h0)
                any_nonzero = 1'b1;
            results_s = {results_s, $sformatf("%s0x%02h", p ? "," : "", observed[7:0])};
        end

        family_check("CHK-RUNBIST-RESPONSE", "distinct RUNBIST scan responses",
                     64'(seen_results.num() > 1), 64'h1,
                     $sformatf("patterns=%0d results=%s", patterns.size(), results_s));
        family_check("CHK-RUNBIST-RESPONSE", "nonzero RUNBIST scan response",
                     64'(any_nonzero), 64'h1,
                     $sformatf("results=%s", results_s));
        finalize_family_checker();
    endtask

endclass : dtp_jtag_runbist_test_seq
