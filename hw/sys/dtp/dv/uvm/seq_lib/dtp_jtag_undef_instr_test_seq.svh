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
  // UNDEFINED_BYPASS_INSTRS): the UNDEFINED_BYPASS_* and RISCV_RESERVED_*
  // members of dtp_jtag_instr_e, in encoding order.
  protected function void undefined_opcodes(ref bit [IrWidth-1:0] opcodes[$]);
    dtp_jtag_instr_e instr = instr.first();
    opcodes.delete();
    do begin
      string name = instr.name();
      if (name.substr(0, 16) == "UNDEFINED_BYPASS_" || name.substr(0, 14) == "RISCV_RESERVED_")
        opcodes.push_back(instr);
      instr = instr.next();
    end while (instr != instr.first());
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
    log_step("1", "Reset TAP");
    reset_to_tlr();

    log_step("2", "Each reserved opcode decodes, scans the bypass, raises no host select");
    foreach (opcodes[i]) begin
      log_iteration(i + 1, opcodes.size(), $sformatf("reserved opcode 0x%02h", opcodes[i]));
      check_bypass_no_host_select(opcodes[i], 64'hA5A5_5A5A_C3C3_3C3C);
      check_bypass_delay(opcodes[i], random_pattern(32), 32);
    end

    log_step("3", "Debug-TDR pin outputs show the reset image");
    snapshot_debug_outputs(snapshot);
    debug_output_defaults(defaults);
    check_debug_outputs(NoHostSelectCheckId, snapshot, defaults,
                        "after every reserved-opcode scan");

    log_step("4", "Seeded opcode sample: directed-pattern bypass sweep");
    sample_count = (random_count < opcodes.size()) ? random_count : opcodes.size();
    opcodes.shuffle();
    for (int unsigned i = 0; i < sample_count; i++) check_bypass_patterns(opcodes[i], 32);
    finalize_family_checker();
  endtask

endclass : dtp_jtag_undef_instr_test_seq
