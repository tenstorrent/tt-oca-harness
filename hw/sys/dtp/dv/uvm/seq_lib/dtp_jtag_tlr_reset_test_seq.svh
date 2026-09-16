// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_tlr_reset_test scenario sequence — TMS-high walk to
// Test-Logic-Reset against the TAP reference model (the SV port of the
// cocotb dtp_jtag_tlr_reset_test_seq):
//   * from four distinct start states (Run-Test/Idle, Shift-IR, Shift-DR,
//     and a seeded Pause-IR/Pause-DR pick) with DEBUG_CONTROL and IC_RESET
//     (reset_hold = 1) written to non-default images and BYPASS loaded, walk
//     a seeded 5..8 consecutive TMS=1 cycles and prove the TAP lands in
//     Test-Logic-Reset (CHK-TAP-TLR-TMS5);
//   * a DR scan right after TLR (no IR load) must read the
//     device-identification register: TLR re-selects IDCODE over the loaded
//     BYPASS (CHK-TAP-TLR-IDCODE);
//   * the debug-TDR pin outputs and the DEBUG_CONTROL / IC_RESET readbacks
//     must show their defaults (CHK-TLR-TDR-DEFAULT), and IDCODE loaded by
//     an IR scan must read back, proving instruction-register access resumes
//     (CHK-TLR-RESUME);
//   * CHK-NONVAC rejects a degenerate pass (repeated start states, sub-5
//     walks, or missed IDCODE restores).
// Per-cycle walk legality lives in the env's dtp_tap_fsm_checker (aggregate
// CHK-TAP-STATE armed by the test). +DTP_JTAG_TAP_CHECKER_NEGATIVE arms a
// WRONG expected IDCODE so the run must FAIL (the same convention as
// dtp_sanity_test_seq), proving the TLR-selects-IDCODE evidence path rejects
// a bad expectation end to end.
//
// The scan-count cross-check is disabled (cocotb use_monitor=False parity):
// both the navigation into the Pause states and the TMS-high walk out of
// the Shift states cross Shift -> Exit1, publishing partial scans the
// sequence cannot count.

class dtp_jtag_tlr_reset_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_tlr_reset_test_seq)

  localparam string TdrDefaultCheckId = "CHK-TLR-TDR-DEFAULT";
  localparam string ResumeCheckId = "CHK-TLR-RESUME";

  protected bit [31:0] m_expected_idcode = DtpDefaultIdcode;

  function new(string name = "dtp_jtag_tlr_reset_test_seq");
    super.new(name);
  endfunction

  // Pin image of the programmed TDRs: boot stall, its override, and the CLA
  // clock-stop enable set; an active (0) slice enable drives {ovrd=1,
  // ctrl_n=0}.
  protected static function void programmed_debug_outputs(output bit [63:0] outputs[string]);
    outputs["stop_clks"]                = 64'd0;
    outputs["cla_clock_stop_en"]        = 64'd1;
    outputs["jtag_boot_stall"]          = 64'd1;
    outputs["jtag_boot_stall_ovrd"]     = 64'd1;
    outputs["jtag_ic_reset_smc_ovrd"]   = 64'd1;
    outputs["jtag_ic_reset_smc_ctrl_n"] = 64'd0;
    outputs["jtag_ic_reset_sep_ovrd"]   = 64'd1;
    outputs["jtag_ic_reset_sep_ctrl_n"] = 64'd0;
    outputs["jtag_ic_reset_ext_ovrd"]   = 64'd1;
    outputs["jtag_ic_reset_ext_ctrl_n"] = 64'd0;
  endfunction

  // Write non-default DEBUG_CONTROL and IC_RESET images; the pins follow
  // them.
  protected task program_debug_tdrs();
    bit [63:0] packed_value;
    bit [63:0] snapshot[string];
    bit [63:0] expected[string];
    write_debug_control(pack_debug_control(
                        .boot_stall(1'b1), .boot_stall_ovrd(1'b1), .cla_clock_stop_en(1'b1)));
    write_ic_reset(1'b1, '0, '0, packed_value);
    wait_sys_cycles();
    snapshot_debug_outputs(snapshot);
    programmed_debug_outputs(expected);
    check_debug_outputs(TdrDefaultCheckId, snapshot, expected, "programmed before TLR");
  endtask

  // Pin outputs and TDR readbacks at their defaults after Test-Logic-Reset.
  protected task check_tdr_defaults(string context_s);
    bit [63:0] snapshot[string];
    bit [63:0] expected[string];
    bit [63:0] observed;
    bit [63:0] default_ic_reset = bit_mask(IcResetLen);
    wait_sys_cycles();
    snapshot_debug_outputs(snapshot);
    debug_output_defaults(expected);
    check_debug_outputs(TdrDefaultCheckId, snapshot, expected, context_s);
    read_debug_control(observed);
    family_check(TdrDefaultCheckId, "DEBUG_CONTROL readback", observed, 64'd0, context_s);
    read_ic_reset(observed, default_ic_reset);
    family_check(TdrDefaultCheckId, "IC_RESET readback", observed, default_ic_reset, context_s);
  endtask

  // From `state` with the TDRs programmed and BYPASS loaded, walk TMS high
  // into TLR and judge the reset.
  protected task walk_to_tlr(input ocah_jtag_tap_state_e state, output int unsigned ones,
                             output bit restored);
    bit [63:0] observed;
    string ctx;
    ones = $urandom_range(8, 5);
    `uvm_info(get_type_name(), $sformatf("TLR walk: start=%s tms_ones=%0d", state.name(), ones),
              UVM_LOW)
    reset_to_tlr();
    program_debug_tdrs();
    load_ir(BYPASS_INSTR);
    goto_state(state);
    check_state(tap_state_e'(16'h1 << int'(state)), "jtag_tlr_chk", $sformatf(
                "start state %s before TMS-high walk", state.name()));

    repeat (ones) step(1'b1);
    ctx = $sformatf("from=%s tms_ones=%0d", state.name(), ones);
    if (m_family != null) void'(m_family.check_tms_ones_to_tlr(ones, tb_vif.tap_state, ctx));
    check_state(TEST_LOGIC_RESET, "jtag_tlr_chk", {"after TMS-high walk ", ctx});

    // TLR must re-select the device-identification register over the
    // loaded BYPASS: DR scan with no IR load reads IDCODE.
    step(1'b0);  // TLR -> RTI: scan legs start from Run-Test/Idle
    shift_dr(64'h0, 32, observed);
    family_check("CHK-TAP-TLR-IDCODE", "DR scan after TLR, no IR load", observed[31:0],
                 m_expected_idcode, ctx);
    restored = (observed[31:0] == DtpDefaultIdcode);

    check_tdr_defaults({"after TLR ", ctx});
    load_ir(IDCODE_INSTR);
    shift_dr(64'h0, 32, observed);
    family_check(ResumeCheckId, "IDCODE by IR scan after TLR", observed[31:0], DtpDefaultIdcode,
                 ctx);
  endtask

  task body();
    ocah_jtag_tap_state_e states[4];
    int unsigned ones_counts[$];
    int unsigned min_ones[$];
    int unsigned idcode_ok = 0;
    bit unique_states = 1'b1;
    string required[$];

    seed_scenario_rng();
    scan_builder = null;
    required = {"CHK-TAP-RESET-TLR", "CHK-TAP-TLR-TMS5", "CHK-TAP-TLR-IDCODE", TdrDefaultCheckId,
                    ResumeCheckId, "CHK-NONVAC"};
    attach_family_checker(required);

    m_expected_idcode = DtpDefaultIdcode;
    if (test_cfg.tap_checker_negative) begin
      m_expected_idcode ^= 32'h2;
      `uvm_info(get_type_name(),
                $sformatf(
                    "NEGATIVE VALIDATION: arming wrong expected IDCODE 0x%08h instead of 0x%08h",
                    m_expected_idcode, DtpDefaultIdcode), UVM_LOW)
    end

    states[0] = OCAH_JTAG_RUN_TEST_IDLE;
    states[1] = OCAH_JTAG_SHIFT_IR;
    states[2] = OCAH_JTAG_SHIFT_DR;
    states[3] = $urandom_range(1) ? OCAH_JTAG_PAUSE_IR : OCAH_JTAG_PAUSE_DR;

    foreach (states[s]) begin
      int unsigned ones;
      bit restored;
      `uvm_info(get_type_name(), $sformatf("TLR pass %0d/4: start=%s", s + 1, states[s].name()),
                UVM_LOW)
      walk_to_tlr(states[s], ones, restored);
      ones_counts.push_back(ones);
      if (restored) idcode_ok++;
    end

    foreach (states[i])
      for (int unsigned j = i + 1; j < 4; j++) if (states[i] == states[j]) unique_states = 1'b0;
    min_ones = ones_counts.min();
    if (m_family != null)
      void'(m_family.expect_true(
          "CHK-NONVAC",
          unique_states && (min_ones[0] >= 5) && (idcode_ok == 4),
          $sformatf(
              "unique_start_states=%0d min_tms_ones=%0d idcode_restored=%0d/4",
              unique_states,
              min_ones[0],
              idcode_ok)
      ));
    finalize_family_checker();
  endtask

endclass : dtp_jtag_tlr_reset_test_seq
