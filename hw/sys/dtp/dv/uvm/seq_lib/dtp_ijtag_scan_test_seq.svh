// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// iJTAG SIB/DFT/DFD scan scenarios — the SV analogue of the cocotb
// dtp_ijtag_scan_test_seq. One parameterized sequence, dispatched on
// `scenario`:
//
//   sib_all_off   a seeded open set first, then all SIBs closed stays
//                 closed under any seeded gating mask
//   sib_all_on    all SIBs open, then each direct disable gates its SIB
//                 in a seeded order while the others stay effective
//   sib_random    exhaustive 8-pattern sweep plus 16 seeded pattern/mask
//                 combinations
//   dft           secure/non-secure DFT access, cross-resource isolation,
//                 and stored-state preservation across a gate
//   dfd           DFD access, direct-disable gate, seeded patterns, and
//                 stored-state preservation across a gate
//
// Every pattern is proved by check_ijtag_pattern: a composed program scan
// carrying seeded instrument values, then a marker scan under a temporal
// window that yields the control evidence (CHK-SCAN-WIN), the measured
// chain latency (CHK-SCAN-LEN), and the captured SIB states and instrument
// registers against the SIB model (CHK-SCAN-CHAIN).

class dtp_ijtag_scan_test_seq extends dtp_scan_base_test_seq;
  `uvm_object_utils(dtp_ijtag_scan_test_seq)

  // Selected by the test before start(); body() dispatches on it.
  string scenario = "sib_all_off";

  function new(string name = "dtp_ijtag_scan_test_seq");
    super.new(name);
  endfunction

  // Prove a gated Update-DR does not modify stored SIB state and that
  // access resumes without TAP reset after the disable clears.
  protected task check_stored_sib_across_gate(
      int unsigned sib, bit [DtpIjtagSibCount-1:0] open_pattern,
      sep_lifecycle_ctrl_pkg::dbg_disable_t gate_mask, string context_s);
    // Baseline: everything enabled, all SIBs closed.
    check_ijtag_pattern(3'b000, '0, {context_s, ".baseline"});
    // Attempt to open the target SIB while its disable is asserted.
    set_dbg_disable_full(gate_mask);
    program_ijtag_sibs(open_pattern, gate_mask, {context_s, ".gated_open_attempt"});
    // Release the disable without any reset: the gated open attempt must
    // not have stuck (a pre-staged open activating on release would be a
    // delayed-replay hazard).
    enable_all_debug();
    check_ijtag_all_closed('0, {context_s, ".post_release"});
    // Resume without reset: a sanctioned open now succeeds.
    check_ijtag_pattern(open_pattern, '0, {context_s, ".resume"});
  endtask

  protected task run_sib_all_off();
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    // A seeded open pattern first, so the all-off captures and the
    // collapse to the three SIB bits are a transition from open SIBs.
    bit [DtpIjtagSibCount-1:0] open_pattern = DtpIjtagSibCount'($urandom_range(7, 1));
    `uvm_info(get_type_name(), "iJTAG SIB all-off", UVM_LOW)
    `uvm_info(get_type_name(), $sformatf(
                                   "Step 1: open a seeded SIB set 0b%03b, then close every SIB",
                                   open_pattern), UVM_LOW)
    check_ijtag_pattern(open_pattern, '0, "all_off.open_seed");
    check_ijtag_pattern(3'b000, '0, "all_off.nominal");
    // Seeded per-pass disable mask: with every SIB closed, any lifecycle
    // gating state must leave the outcome identical (closed stays closed).
    d = '0;
    d.dft_secure    = bit'($urandom_range(1));
    d.dft_nonsecure = bit'($urandom_range(1));
    d.dfd           = bit'($urandom_range(1));
    `uvm_info(get_type_name(),
              $sformatf("Step 2: close every SIB again under the disable mask 0x%03h", d), UVM_LOW)
    check_ijtag_pattern(3'b000, d, "all_off.random_disable");
    check_ijtag_all_closed(d, "all_off.recheck");
  endtask

  protected task run_sib_all_on();
    sep_lifecycle_ctrl_pkg::dbg_disable_t gate_masks[4];
    int unsigned order[4] = '{0, 1, 2, 3};
    `uvm_info(get_type_name(), "iJTAG SIB all-on", UVM_LOW)
    check_ijtag_pattern(3'b111, '0, "all_on.nominal");
    gate_masks[0] = '0;
    gate_masks[0].dft_secure    = 1'b1;
    gate_masks[1] = '0;
    gate_masks[1].dft_nonsecure = 1'b1;
    gate_masks[2] = '0;
    gate_masks[2].dfd           = 1'b1;
    gate_masks[3] = '0;
    gate_masks[3].dft_secure    = 1'b1;
    gate_masks[3].dft_nonsecure = 1'b1;
    gate_masks[3].dfd           = 1'b1;
    // Seeded per-pass order: each loop exercises a different gate
    // sequence.
    for (int unsigned i = 3; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      int unsigned tmp = order[i];
      order[i] = order[j];
      order[j] = tmp;
    end
    foreach (order[i])
      check_ijtag_pattern(3'b111, gate_masks[order[i]], $sformatf("all_on.gated#%0d", order[i]));
    // Full chain and scan controls again once every disable is clear.
    check_ijtag_pattern(3'b111, '0, "all_on.restore");
  endtask

  protected task run_sib_random();
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    `uvm_info(get_type_name(), "iJTAG SIB deterministic and random sweep", UVM_LOW)
    for (int unsigned pattern = 0; pattern < 8; pattern++)
      check_ijtag_pattern(3'(pattern), '0, $sformatf("sweep.pattern_%03b", pattern));
    for (int unsigned idx = 0; idx < 16; idx++) begin
      bit [2:0] pattern = 3'($urandom_range(7));
      d = '0;
      d.dft_secure    = bit'($urandom_range(1));
      d.dft_nonsecure = bit'($urandom_range(1));
      d.dfd           = bit'($urandom_range(1));
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/16: pattern=0b%03b dbg_disable=0x%03h", idx + 1, pattern, d),
                UVM_LOW)
      check_ijtag_pattern(pattern, d, $sformatf("random.iter_%0d", idx));
    end
  endtask

  protected task run_dft();
    sep_lifecycle_ctrl_pkg::dbg_disable_t gate;
    typedef struct {
      string    label;
      bit [2:0] pattern;
      bit       gate_secure;
      bit       gate_nonsecure;
    } dft_case_t;
    dft_case_t cases[4];
    int unsigned order[4] = '{0, 1, 2, 3};
    `uvm_info(get_type_name(), "iJTAG DFT secure/non-secure access", UVM_LOW)
    check_ijtag_pattern(3'b010, '0, "dft.nonsecure_only");
    check_ijtag_pattern(3'b100, '0, "dft.secure_only");
    check_ijtag_pattern(3'b110, '0, "dft.parallel");
    cases[0] = '{"secure_gated", 3'b100, 1'b1, 1'b0};
    cases[1] = '{"nonsecure_gated", 3'b010, 1'b0, 1'b1};
    // Cross-resource isolation: gating one DFT SIB must leave the other
    // DFT SIB accessible.
    cases[2] = '{"secure_gated_nonsecure_open", 3'b110, 1'b1, 1'b0};
    cases[3] = '{"nonsecure_gated_secure_open", 3'b110, 1'b0, 1'b1};
    // Seeded per-pass order: each loop exercises a different gate
    // sequence.
    for (int unsigned i = 3; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      int unsigned tmp = order[i];
      order[i] = order[j];
      order[j] = tmp;
    end
    foreach (order[i]) begin
      gate = '0;
      gate.dft_secure    = cases[order[i]].gate_secure;
      gate.dft_nonsecure = cases[order[i]].gate_nonsecure;
      check_ijtag_pattern(cases[order[i]].pattern, gate, {"dft.gated.", cases[order[i]].label});
    end
    gate = '0;
    gate.dft_nonsecure = 1'b1;
    check_stored_sib_across_gate(int'(IJ_DFT), 3'b010, gate, "dft.stored");
  endtask

  protected task run_dfd();
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    `uvm_info(get_type_name(), "iJTAG DFD access and direct-disable gate", UVM_LOW)
    check_ijtag_pattern(3'b001, '0, "dfd.enabled");
    d = '0;
    d.dfd = 1'b1;
    check_ijtag_pattern(3'b001, d, "dfd.gated");
    for (int unsigned idx = 0; idx < 8; idx++) begin
      bit [2:0] pattern = 3'b001 | (3'($urandom_range(3)) << 1);
      d = '0;
      d.dfd = bit'($urandom_range(1));
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/8: pattern=0b%03b dfd_disable=%0d", idx + 1, pattern, d.dfd),
                UVM_LOW)
      check_ijtag_pattern(pattern, d, $sformatf("dfd.random_%0d", idx));
    end
    d = '0;
    d.dfd = 1'b1;
    check_stored_sib_across_gate(int'(IJ_DFD), 3'b001, d, "dfd.stored");
  endtask

  task body();
    // Per-pass evidence every iJTAG pass must record (cocotb twin:
    // dtp_ijtag_scan_test_seq.py).
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-LEN", "CHK-SCAN-CHAIN"};
    seed_scenario_rng();
    // Scenario-owned Shift-x exits: skip the scan-count cross-check.
    attach_family_checker(required, 1'b0);
    enable_all_debug();
    reset_to_tlr();
    case (scenario)
      "sib_all_off": run_sib_all_off();
      "sib_all_on":  run_sib_all_on();
      "sib_random":  run_sib_random();
      "dft":         run_dft();
      "dfd":         run_dfd();
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown iJTAG scenario %s", scenario))
    endcase
    enable_all_debug();
    program_ijtag_sibs(3'b000, '0, "cleanup");
    finalize_family_checker();
  endtask

endclass : dtp_ijtag_scan_test_seq
