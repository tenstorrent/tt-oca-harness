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
//   sib_random    every combination of closed, open, and gated SIBs (the
//                 27 ungated open sets over the 8 disable masks) plus 16
//                 seeded pattern/mask combinations
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
    string gated_controls[$];
    // Baseline: everything enabled, all SIBs closed.
    check_ijtag_pattern(3'b000, '0, {context_s, ".baseline"});
    // Attempt to open the target SIB while its disable is asserted: its
    // four scan controls stay quiet across the whole attempt.
    set_dbg_disable_full(gate_mask);
    ijtag_gated_controls(gate_mask, gated_controls);
    program_ijtag_sibs_quiet(open_pattern, gate_mask, gated_controls, {
                             context_s, ".gated_open_attempt"});
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
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++)
      dtp_dbg_path_set(d, dtp_ijtag_sib_dbg_path(s), bit'($urandom_range(1)));
    `uvm_info(get_type_name(),
              $sformatf("Step 2: close every SIB again under the disable mask 0x%03h", d), UVM_LOW)
    check_ijtag_pattern(3'b000, d, "all_off.random_disable");
    check_ijtag_all_closed(d, "all_off.recheck");
  endtask

  protected task run_sib_all_on();
    sep_lifecycle_ctrl_pkg::dbg_disable_t gate_masks[4];
    int unsigned order[4] = '{0, 1, 2, 3};
    `uvm_info(get_type_name(), "iJTAG SIB all-on", UVM_LOW)
    check_host_scan_out_reset("all_on.reset");
    check_ijtag_pattern(3'b111, '0, "all_on.nominal");
    // One mask per SIB, then all three together.
    gate_masks[3] = '0;
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) begin
      gate_masks[s] = dtp_dbg_disable_only(dtp_ijtag_sib_dbg_path(s));
      dtp_dbg_path_set(gate_masks[3], dtp_ijtag_sib_dbg_path(s));
    end
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
    int unsigned masks[$] = {0, 1, 2, 3, 4, 5, 6, 7};
    `uvm_info(get_type_name(), "iJTAG SIB gating sweep and random patterns", UVM_LOW)
    // Every combination of SIB states, each SIB closed, open, or gated:
    // every disable mask of the three SIB fields in a seeded order, and
    // under each mask every open set of the ungated SIBs. A gated SIB's
    // request bit is drawn; it stays closed either way.
    shuffle(masks);
    foreach (masks[m]) begin
      bit [DtpIjtagSibCount-1:0] mask = DtpIjtagSibCount'(masks[m]);
      d = '0;
      for (int unsigned s = 0; s < DtpIjtagSibCount; s++)
      dtp_dbg_path_set(d, dtp_ijtag_sib_dbg_path(s), mask[DtpIjtagSibCount-1-s]);
      `uvm_info(get_type_name(), $sformatf(
                "Step %0d: SIB disable mask 0b%03b, every ungated open set", m + 1, mask), UVM_LOW)
      for (int unsigned pattern = 0; pattern < 8; pattern++) begin
        bit [DtpIjtagSibCount-1:0] open_set = DtpIjtagSibCount'(pattern);
        if ((open_set & mask) != '0) continue;
        check_ijtag_pattern(open_set | (DtpIjtagSibCount'($urandom_range(7)) & mask), d, $sformatf(
                            "sweep.mask_%03b.open_%03b", mask, open_set));
      end
    end
    for (int unsigned idx = 0; idx < 16; idx++) begin
      bit [2:0] pattern = 3'($urandom_range(7));
      d = '0;
      for (int unsigned s = 0; s < DtpIjtagSibCount; s++)
      dtp_dbg_path_set(d, dtp_ijtag_sib_dbg_path(s), bit'($urandom_range(1)));
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
      dtp_dbg_path_set(gate, DTP_DBG_PATH_DFT_SECURE, cases[order[i]].gate_secure);
      dtp_dbg_path_set(gate, DTP_DBG_PATH_DFT_NONSECURE, cases[order[i]].gate_nonsecure);
      check_ijtag_pattern(cases[order[i]].pattern, gate, {"dft.gated.", cases[order[i]].label});
    end
    gate = dtp_dbg_disable_only(DTP_DBG_PATH_DFT_NONSECURE);
    check_stored_sib_across_gate(int'(IJ_DFT), 3'b010, gate, "dft.stored");
  endtask

  protected task run_dfd();
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    `uvm_info(get_type_name(), "iJTAG DFD access and direct-disable gate", UVM_LOW)
    check_ijtag_pattern(3'b001, '0, "dfd.enabled");
    d = dtp_dbg_disable_only(DTP_DBG_PATH_DFD);
    check_ijtag_pattern(3'b001, d, "dfd.gated");
    for (int unsigned idx = 0; idx < 8; idx++) begin
      bit [2:0] pattern = 3'b001 | (3'($urandom_range(3)) << 1);
      bit dfd_disabled = bit'($urandom_range(1));
      d = '0;
      dtp_dbg_path_set(d, DTP_DBG_PATH_DFD, dfd_disabled);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/8: pattern=0b%03b dfd_disable=%0d", idx + 1, pattern, dfd_disabled),
                UVM_LOW)
      check_ijtag_pattern(pattern, d, $sformatf("dfd.random_%0d", idx));
    end
    d = dtp_dbg_disable_only(DTP_DBG_PATH_DFD);
    check_stored_sib_across_gate(int'(IJ_DFD), 3'b001, d, "dfd.stored");
  endtask

  task body();
    // Per-pass evidence every iJTAG pass must record (cocotb twin:
    // dtp_ijtag_scan_test_seq.py).
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-LEN", "CHK-SCAN-CHAIN"};
    if (scenario == "sib_all_on") required.push_back("CHK-SCAN-RESET");
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
