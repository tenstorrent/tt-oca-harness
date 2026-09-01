// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC fabric JTAG2AXI_CAPS scenario: the 14-bit capability TDR must report
// the AXI4 56/64 geometry with depth-3 pipelines, stay stable across
// repeated reads and instruction switches, and ignore write attempts.
// Mirrors the cocotb dtp_dbg_smc_jtag2axi_caps_test_seq.

class dtp_dbg_smc_jtag2axi_caps_test_seq extends dtp_debug_tdr_base_test_seq;
    `uvm_object_utils(dtp_dbg_smc_jtag2axi_caps_test_seq)

    function new(string name = "dtp_dbg_smc_jtag2axi_caps_test_seq");
        super.new(name);
    endfunction

    task body();
        string required[$] = {"CHK-TAP-RESET-TLR", "CHK-CAPS", "CHK-CAPS-RO"};
        seed_scenario_rng();
        attach_family_checker(required);
        reset_to_tlr();
        check_jtag2axi_caps(6'(SMC_JTAG2AXI_CAPS_INSTR), "SMC_JTAG2AXI_CAPS",
                            .bus_type(1'b0), .addr_width(56),
                            .data_width_bits(64));
        finalize_family_checker();
    endtask

endclass : dtp_dbg_smc_jtag2axi_caps_test_seq
