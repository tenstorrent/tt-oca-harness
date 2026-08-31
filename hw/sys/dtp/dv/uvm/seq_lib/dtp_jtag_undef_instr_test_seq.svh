// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_undef_instr_test scenario sequence: every reserved/undefined IR
// opcode (0x0F, 0x10-0x17, 0x2D-0x3C) must select the one-bit BYPASS path.
// Each opcode gets a fixed 64-bit and a seeded random 32-bit delay check;
// a seeded sample of opcodes additionally runs the full directed-pattern
// sweep. Mirrors the cocotb scenario, which checks inline without a family
// evidence set (the delay compares fail the run directly).

class dtp_jtag_undef_instr_test_seq extends dtp_jtag_cmd_lib_seq;
    `uvm_object_utils(dtp_jtag_undef_instr_test_seq)

    function new(string name = "dtp_jtag_undef_instr_test_seq");
        super.new(name);
    endfunction

    // Reserved/undefined opcodes that fall back to BYPASS (dtp_types.py
    // UNDEFINED_BYPASS_INSTRS).
    protected function void undefined_opcodes(ref bit [IrWidth-1:0] opcodes[$]);
        opcodes.delete();
        opcodes.push_back(6'h0F);
        for (int unsigned op = 6'h10; op <= 6'h17; op++)
            opcodes.push_back(6'(op));
        for (int unsigned op = 6'h2D; op <= 6'h3C; op++)
            opcodes.push_back(6'(op));
    endfunction

    task body();
        bit [IrWidth-1:0] opcodes[$];
        int unsigned sample_count;

        seed_scenario_rng();
        undefined_opcodes(opcodes);
        reset_to_tlr();

        foreach (opcodes[i]) begin
            `uvm_info(get_type_name(), $sformatf(
                "Checking undefined opcode 0x%02h falls back to BYPASS", opcodes[i]),
                UVM_LOW)
            check_bypass_delay(opcodes[i], 64'hA5A5_5A5A_C3C3_3C3C);
            check_bypass_delay(opcodes[i], random_pattern(32), 32);
        end

        // Seeded sample without replacement: full pattern sweep on a subset.
        sample_count = (random_count < opcodes.size()) ? random_count : opcodes.size();
        opcodes.shuffle();
        for (int unsigned i = 0; i < sample_count; i++)
            check_bypass_patterns(opcodes[i], 32);
    endtask

endclass : dtp_jtag_undef_instr_test_seq
