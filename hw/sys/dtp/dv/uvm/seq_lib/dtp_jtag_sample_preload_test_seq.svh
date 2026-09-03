// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SAMPLE/PRELOAD scan-loopback scenario: directed/random loopback patterns
// through the compact BSR chain, IR churn through BYPASS, and one directed
// loopback after the churn. Mirrors the cocotb dtp_jtag_sample_preload_test_seq.

class dtp_jtag_sample_preload_test_seq extends dtp_jtag_base_test_seq;
    `uvm_object_utils(dtp_jtag_sample_preload_test_seq)

    function new(string name = "dtp_jtag_sample_preload_test_seq");
        super.new(name);
    endfunction

    task body();
        string required[$] = {"CHK-TAP-RESET-TLR", "CHK-IR-DECODE", "CHK-BSR-LOOPBACK",
                              "CHK-SCAN-COUNT", "CHK-SCAN-IR-LEN", "CHK-SCAN-DR-LEN",
                              "CHK-NONVAC"};
        seed_scenario_rng();
        attach_family_checker(required);
        reset_to_tlr();
        check_loopback_patterns(6'(SAMPLE_PRELOAD_INSTR));
        load_ir(6'(BYPASS_INSTR));
        check_loopback_scan(6'(SAMPLE_PRELOAD_INSTR), 64'h3C);
        finalize_family_checker();
    endtask

endclass : dtp_jtag_sample_preload_test_seq
