// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_undef_instr_test scenario sequence: every reserved/undefined IR
// opcode (0x0F, 0x10-0x17, 0x2D-0x3C) decodes as itself and selects the
// one-bit BYPASS path. Each opcode gets a fixed 64-bit delay check under a
// window proving none of the four instruction-qualified host chain selects
// rises (CHK-UNDEF-NO-SELECT) and a seeded random 32-bit delay check; the
// debug-TDR pin outputs must show the reset image afterwards, and a
// seeded sample of opcodes additionally runs the full directed-pattern
// sweep. Mirrors the cocotb dtp_jtag_undef_instr_test_seq.

class dtp_jtag_undef_instr_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_undef_instr_test_seq)

  function new(string name = "dtp_jtag_undef_instr_test_seq");
    super.new(name);
  endfunction

  // Reserved/undefined opcodes that fall back to BYPASS (dtp_types.py
  // UNDEFINED_BYPASS_INSTRS).
  protected function void undefined_opcodes(ref bit [IrWidth-1:0] opcodes[$]);
    opcodes.delete();
    opcodes.push_back(6'h0F);
    for (int unsigned op = 6'h10; op <= 6'h17; op++) opcodes.push_back(6'(op));
    for (int unsigned op = 6'h2D; op <= 6'h3C; op++) opcodes.push_back(6'(op));
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR",
                          "CHK-IR-DECODE",
                          "CHK-BYPASS-DELAY",
                          "CHK-UNDEF-NO-SELECT",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"};
    bit [IrWidth-1:0] opcodes[$];
    int unsigned sample_count;
    bit [63:0] snapshot[string];
    bit [63:0] defaults[string];

    seed_scenario_rng();
    attach_family_checker(required);
    undefined_opcodes(opcodes);
    `uvm_info(get_type_name(), "Step 1: Reset TAP", UVM_LOW)
    reset_to_tlr();

    `uvm_info(get_type_name(),
              "Step 2: Each reserved opcode decodes, scans the bypass, raises no host select",
              UVM_LOW)
    foreach (opcodes[i]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: reserved opcode 0x%02h", i + 1, opcodes.size(), opcodes[i]),
                UVM_LOW)
      check_bypass_no_host_select(opcodes[i], 64'hA5A5_5A5A_C3C3_3C3C);
      check_bypass_delay(opcodes[i], random_pattern(32), 32);
    end

    `uvm_info(get_type_name(), "Step 3: Debug-TDR pin outputs show the reset image", UVM_LOW)
    snapshot_debug_outputs(snapshot);
    debug_output_defaults(defaults);
    check_debug_outputs(NoHostSelectCheckId, snapshot, defaults,
                        "after every reserved-opcode scan");

    `uvm_info(get_type_name(), "Step 4: Seeded opcode sample: directed-pattern bypass sweep",
              UVM_LOW)
    sample_count = (random_count < opcodes.size()) ? random_count : opcodes.size();
    opcodes.shuffle();
    for (int unsigned i = 0; i < sample_count; i++) check_bypass_patterns(opcodes[i], 32);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_undef_instr_test_seq
