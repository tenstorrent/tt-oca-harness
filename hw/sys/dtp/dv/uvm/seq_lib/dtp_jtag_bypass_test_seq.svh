// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_bypass_test scenario sequence: checks both DTP BYPASS instruction
// encodings (IR 0x00 and IR 0x3F) with directed + seeded random patterns per
// opcode plus one focused 8-bit case, recording per-opcode expected-TDO
// evidence (CHK-BYPASS-00 / CHK-BYPASS-3F), the reference-model 1-TCK
// latency contract (CHK-BYPASS-LATENCY), and suite-level non-vacuity: both
// opcodes exercised, at least six distinct patterns, and at least one
// observation whose delayed image differs from a direct passthrough.

class dtp_jtag_bypass_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_bypass_test_seq)

  function new(string name = "dtp_jtag_bypass_test_seq");
    super.new(name);
  endfunction

  // One BYPASS case: scan, then per-opcode expected-TDO and latency
  // evidence. Returns 1 when the delayed image differs from a direct
  // passthrough (the observation that proves the delay is real).
  protected task run_bypass_case(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                                 input int unsigned width, input string label, output bit delayed);
    bit [63:0] observed, expected;
    string context_s;
    load_ir(instr);
    shift_dr(pattern, width, observed);
    observed &= bit_mask(width);
    expected = ocah_jtag_checker::predict_bypass_tdo(pattern, width);
    context_s = $sformatf("case=%s opcode=0x%02h width=%0d pattern=0x%0h",
                              label, instr, width, pattern);
    // Checker-ID grammar is uppercase-only; name the two encodings
    // explicitly rather than formatting the opcode.
    family_check((instr == BYPASS_ALT_INSTR) ? "CHK-BYPASS-00" : "CHK-BYPASS-3F", $sformatf(
                 "bypass TDO for IR 0x%02h", instr), observed, expected, context_s);
    void'(m_family.check_bypass_latency(observed, pattern, width, 1'b0, context_s));
    delayed = (observed === expected) && (observed !== (pattern & bit_mask(width)));
  endtask

  task body();
    bit [IrWidth-1:0] opcodes[2] = '{BYPASS_ALT_INSTR, BYPASS_INSTR};
    int unsigned delayed_observations = 0;
    int unsigned case_count = 0;
    bit seen_patterns[bit [63:0]];
    bit seen_opcodes[bit [IrWidth-1:0]];
    bit delayed;

    seed_scenario_rng();
    attach_family_checker({
                          "CHK-BYPASS-00",
                          "CHK-BYPASS-3F",
                          "CHK-BYPASS-LATENCY",
                          "CHK-TAP-RESET-TLR",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"
                          });
    `uvm_info(get_type_name(),
              $sformatf("DTP BYPASS suite: scenario_seed=%0d random_count=%0d opcodes=0x00,0x3f",
                        scenario_seed, random_count), UVM_LOW)
    reset_to_tlr();

    foreach (opcodes[o]) begin
      bit [63:0] patterns[$];
      directed_patterns(64, patterns);
      foreach (patterns[p]) begin
        `uvm_info(get_type_name(), $sformatf(
                  "case %0d: opcode=0x%02h pattern=0x%016h", case_count + 1, opcodes[o], patterns[p]
                  ), UVM_LOW)
        run_bypass_case(opcodes[o], patterns[p], 64, $sformatf("opcode_%02h_%02d", opcodes[o], p),
                        delayed);
        if (delayed) delayed_observations++;
        seen_patterns[patterns[p]] = 1'b1;
        seen_opcodes[opcodes[o]] = 1'b1;
        case_count++;
      end
      // Focused short-width case per opcode.
      run_bypass_case(opcodes[o], 64'h5A, 8, $sformatf("opcode_%02h_focused", opcodes[o]), delayed);
      if (delayed) delayed_observations++;
      seen_patterns[64'h5A] = 1'b1;
      case_count++;
    end

    void'(m_family.expect_true(
        "CHK-NONVAC",
        (seen_opcodes.num() == 2) && (seen_patterns.num() >= 6) && (delayed_observations > 0),
        $sformatf(
            "seed=%0d cases=%0d opcodes=%0d patterns=%0d delayed_observations=%0d",
            scenario_seed,
            case_count,
            seen_opcodes.num(),
            seen_patterns.num(),
            delayed_observations)
    ));
    finalize_family_checker();
  endtask

endclass : dtp_jtag_bypass_test_seq
