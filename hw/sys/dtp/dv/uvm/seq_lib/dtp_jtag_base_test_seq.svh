// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Basic-JTAG family layer of the DTP scenario sequences: the per-pass
// instruction-family evidence checker and the checked operations built on
// the base virtual sequence (dtp_base_test_seq): bypass delay,
// inverted/zero-length bypass, BSR loopback, decoded-IR compare, TMP_STATUS
// reads, and the scan-control windows (the env dtp_scan_window_monitor
// counts high samples of named dtp_scan_if observables once per TCK cycle
// across one DR scan, so a scenario proves which host chain the loaded
// instruction selects and that the TAP's strobes reach it). Every family
// helper records named CHK-* evidence through a per-pass ocah_jtag_checker
// instead of bare asserts; finalize_family_checker() rejects a pass with
// zero checks or a missing required ID, and cross-checks the Shift-x
// episodes of the DUT's exported TAP state (env scan builder) against the
// sequence's own scan intent (CHK-SCAN-COUNT / CHK-SCAN-IR-LEN /
// CHK-SCAN-DR-LEN / CHK-NONVAC).
// The basic-JTAG, debug-TDR, and scan-network scenarios extend it; the
// cocotb twins are seq_lib/dtp_jtag_base_test_seq.py and
// seq_lib/dtp_jtag_cmd_lib_seq.py.
//
// test_cfg.family_checker_negative (+DTP_JTAG_FAMILY_CHECKER_NEGATIVE) is
// the negative-validation hook: every integer family expectation is
// corrupted (XOR 1) so the run must FAIL, proving the evidence path gates
// pass/fail end to end.

class dtp_jtag_base_test_seq extends dtp_base_test_seq;
  `uvm_object_utils(dtp_jtag_base_test_seq)

  // Compact OSS boundary-scan loopback model length (dtp_tap_device.py):
  // the DUT loops bsr scan_out -> scan_in, so a BSR-instruction DR scan
  // returns the shifted pattern retimed by one TCK.
  localparam int unsigned DtpBsrModelLen = 8;
  // TMP_STATUS TDR: bit 1 = persistence, bit 0 = BYPASS_ESCAPE arm.
  localparam int unsigned TmpStatusLen = 2;
  // dtp_scan_if prefixes of the boundary-scan chain and the non-secure DFT
  // host, and the evidence ID of the quiet host-select window.
  localparam string BsrScanCtrl = "jtag_bsr";
  localparam string DftScanCtrl = "jtag_dft";
  localparam string NoHostSelectCheckId = "CHK-UNDEF-NO-SELECT";

  // Per-pass instruction-family evidence checker (created by
  // attach_family_checker, finalized by finalize_family_checker).
  protected ocah_jtag_checker m_family;
  protected bit               m_family_negative;
  protected bit               m_scan_crosscheck;
  protected int unsigned      m_ir_scan_base;
  protected int unsigned      m_dr_scan_base;
  protected int unsigned      m_expected_ir_widths[$];
  protected int unsigned      m_expected_dr_widths[$];

  function new(string name = "dtp_jtag_base_test_seq");
    super.new(name);
  endfunction

  // ------------------------------------------------------------------
  // Family evidence plumbing.
  // ------------------------------------------------------------------

  // use_scan_crosscheck=0 mirrors the cocotb use_monitor=False sequences:
  // scenarios whose raw TMS stimulus (random walks, state navigation
  // through Shift-x) publishes scan-builder items the sequence cannot
  // count must skip the count cross-check.
  function void attach_family_checker(string required_ids[$], bit use_scan_crosscheck = 1'b1);
    if (test_cfg == null) `uvm_fatal(get_type_name(), "test_cfg not plumbed by the test")
    m_family = ocah_jtag_checker::type_id::create({get_name(), ".family"});
    m_family.name_tag     = "dtp_jtag_family";
    m_family.required_ids = required_ids;
    m_family_negative = test_cfg.family_checker_negative;
    if (m_family_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: family checker expectations will be corrupted", UVM_LOW)
    m_scan_crosscheck = use_scan_crosscheck;
    m_expected_ir_widths.delete();
    m_expected_dr_widths.delete();
    if (scan_builder != null) begin
      // Fresh reconstruction window per pass (the cocotb flow starts a
      // fresh monitor per pass); also keeps the builder's bounded
      // history from saturating across the 16-pass floor.
      scan_builder.clear_scan_history();
      m_ir_scan_base = 0;
      m_dr_scan_base = 0;
    end
  endfunction

  // Record one named family comparison; plain check when unattached.
  function void family_check(string check_id, string name, bit [63:0] observed, bit [63:0] expected,
                             string context_s = "");
    bit [63:0] armed = expected;
    if (m_family == null) begin
      if (observed !== expected)
        `uvm_error(check_id, $sformatf(
                   "%s: expected 0x%0h, got 0x%0h (%s)", name, expected, observed, context_s))
      else
        `uvm_info(check_id, $sformatf("%s: 0x%0h as expected (%s)", name, observed, context_s),
                  UVM_MEDIUM)
      return;
    end
    if (m_family_negative) armed = expected ^ 64'h1;
    void'(m_family.expect_equal(
        check_id, observed, armed, {name, context_s.len() ? " " : "", context_s}
    ));
  endfunction

  // Cross-check the Shift-IR / Shift-DR episodes of the DUT's exported TAP
  // state against the sequence's own scan intent (as many episodes as scans
  // issued, each as long as the width driven), then finalize the per-pass
  // evidence.
  function void finalize_family_checker();
    if (m_family == null) `uvm_fatal(get_type_name(), "family checker was never attached")
    if (m_scan_crosscheck && scan_builder != null) begin
      int unsigned ir_new = scan_builder.dut_ir_shift_lens.size() - m_ir_scan_base;
      int unsigned dr_new = scan_builder.dut_dr_shift_lens.size() - m_dr_scan_base;
      bit counts_match = (ir_new == m_expected_ir_widths.size()) &&
                               (dr_new == m_expected_dr_widths.size());
      void'(m_family.expect_true(
          "CHK-SCAN-COUNT",
          counts_match,
          $sformatf(
              "DUT Shift episodes (ir=%0d, dr=%0d) vs sequence-issued (ir=%0d, dr=%0d)",
              ir_new,
              dr_new,
              m_expected_ir_widths.size(),
              m_expected_dr_widths.size())
      ));
      if (counts_match) begin
        foreach (m_expected_ir_widths[i])
        family_check("CHK-SCAN-IR-LEN", $sformatf("ir_scan#%0d", i + 1),
                     64'(scan_builder.dut_ir_shift_lens[m_ir_scan_base+i]),
                     64'(m_expected_ir_widths[i]), "source=jtag_ptap_state_o");
        foreach (m_expected_dr_widths[i])
        family_check("CHK-SCAN-DR-LEN", $sformatf("dr_scan#%0d", i + 1),
                     64'(scan_builder.dut_dr_shift_lens[m_dr_scan_base+i]),
                     64'(m_expected_dr_widths[i]), "source=jtag_ptap_state_o");
      end
      void'(m_family.expect_true(
          "CHK-NONVAC",
          (ir_new > 0) && (dr_new > 0),
          $sformatf(
              "DUT Shift-IR episodes=%0d Shift-DR episodes=%0d", ir_new, dr_new)
      ));
    end
    m_family.finalize(1'b1);
  endfunction

  // Track the sequence's own scan intent for the finalize cross-check.
  virtual function void note_scan(bit is_ir, int unsigned width);
    if (m_family == null) return;
    if (is_ir) m_expected_ir_widths.push_back(width);
    else m_expected_dr_widths.push_back(width);
  endfunction

  // Route a downstream device's slave-sequence evidence into this pass's
  // family checker (scan scenarios).
  function ocah_jtag_checker family_checker();
    return m_family;
  endfunction

  // ------------------------------------------------------------------
  // TAP entry points.
  // ------------------------------------------------------------------

  // TAP reset with family evidence, ending in Run-Test/Idle (the VIP scan
  // contract starts IR/DR scans from RTI).
  virtual task reset_to_tlr();
    tap_reset_op();
    if (m_family != null) void'(m_family.check_reset_to_tlr(tb_vif.tap_state, "family TAP reset"));
    if (evidence != null)
      void'(evidence.check_reset_to_tlr(tb_vif.tap_state, "after TRST release"));
    check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after TRST release");
    step(1'b0);  // TLR -> RTI
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after TLR->RTI step");
  endtask

  // cocotb dtp_jtag_cmd_lib_seq.reset_to_known_idle parity.
  task reset_to_known_idle();
    reset_to_tlr();
  endtask

  // ------------------------------------------------------------------
  // Observable checks.
  // ------------------------------------------------------------------

  // CHK-IR-DECODE: the exposed decoded-instruction one-hot matches the
  // loaded opcode (dtp_tb_if.inst_decoded mirror).
  task expect_decoded_instruction(dtp_jtag_instr_e instr);
    family_check("CHK-IR-DECODE", "decoded instruction", 64'(tb_vif.inst_decoded),
                 64'h1 << int'(instr), $sformatf("ir=0x%02h", instr));
  endtask

  // Sample one scan-domain observable and record it. TCK-domain observables
  // settle on the falling edge that ends the last step and the driver idles
  // TCK between items, so one system cycle later the sample is race-free
  // and precedes any TCK edge. An X sample is an error in its own right: a
  // zero expectation would otherwise absorb it.
  task check_scan_observable(string check_id, string name, bit expected, string context_s = "");
    logic sampled;
    if (scan_window == null)
      `uvm_fatal(get_type_name(), "scan_window monitor not plumbed by the test")
    wait_sys_cycles(1);
    sampled = scan_window.sample_scan_signal(name);
    if ($isunknown(sampled)) `uvm_error(check_id, $sformatf("%s sampled X (%s)", name, context_s))
    family_check(check_id, name, 64'(sampled === 1'b1), 64'(expected), context_s);
  endtask

  // Record that the DUT's TAP shifted inside the window that just closed:
  // its exported state visited Shift-DR or Shift-IR, so the counts judged
  // next were taken across a scan the DUT performed. A TAP held in reset or
  // a dead state output records zero cycles here and fails.
  function void check_window_shifted(string check_id, string context_s);
    int unsigned cycles;
    if (scan_window == null)
      `uvm_fatal(get_type_name(), "scan_window monitor not plumbed by the test")
    cycles = scan_window.last_dut_shift_cycles();
    family_check(check_id, "window DUT shift cycles nonvacuous", 64'(cycles > 0), 64'd1, $sformatf(
                 "%s dut_shift_cycles=%0d", context_s, cycles));
  endfunction

  // ------------------------------------------------------------------
  // Scan-control windows (env dtp_scan_window_monitor).
  // ------------------------------------------------------------------

  // Begin counting high samples of the named observables once per TCK
  // cycle (falling edge, all controls settled).
  function void start_scan_window(string signals[$]);
    if (scan_window == null)
      `uvm_fatal(get_type_name(), "scan_window monitor not plumbed by the test")
    scan_window.start_window(signals);
  endfunction

  // End the window; return the TCK-cycle count and per-signal high counts.
  function void stop_scan_window(output int unsigned edges, output int unsigned counts[string]);
    if (scan_window == null)
      `uvm_fatal(get_type_name(), "scan_window monitor not plumbed by the test")
    scan_window.stop_window(edges, counts);
  endfunction

  // The four host scan-control observables of one chain prefix.
  static function void scan_ctrl_signals(string prefix, ref string signals[$]);
    signals.push_back({prefix, "_select"});
    signals.push_back({prefix, "_capture_en"});
    signals.push_back({prefix, "_shift_en"});
    signals.push_back({prefix, "_update_en"});
  endfunction

  // Evidence IDs (select, strobes) of one chain's control window.
  static function void scan_ctrl_check_ids(string prefix, output string select_id,
                                           output string ctrl_id);
    if (prefix == DftScanCtrl) begin
      select_id = "CHK-DFT-SIB-SELECT";
      ctrl_id   = "CHK-DFT-SCAN-CTRL";
    end else begin
      select_id = "CHK-BSR-SELECT";
      ctrl_id   = "CHK-BSR-SCAN-CTRL";
    end
  endfunction

  // The instruction-qualified host chain selects: boundary scan and the
  // three iJTAG SIB hosts. The extended STAP host select follows every IR
  // and DR scan path regardless of the instruction, so it is not one of
  // them.
  static function void host_selects(ref string signals[$]);
    signals.push_back("jtag_bsr_select");
    signals.push_back("jtag_dft_secure_select");
    signals.push_back("jtag_dft_select");
    signals.push_back("jtag_dfd_select");
  endfunction

  // DR scan from Run-Test/Idle while a window counts high samples of
  // `signals`.
  task shift_dr_windowed(input bit [63:0] pattern, input int unsigned width,
                         input string signals[$], output bit [63:0] observed,
                         output int unsigned edges, output int unsigned counts[string]);
    start_scan_window(signals);
    shift_dr(pattern, width, observed);
    stop_scan_window(edges, counts);
  endtask

  // Judge one chain's control counts across a `width`-bit DR scan. The scan
  // enters Shift-DR before its first bit, so the TAP's strobes pulse capture
  // once, shift `width` times, and update once; a gated host shows none of
  // them. Select is high only for the chain's own instruction.
  function void check_scan_ctrl_counts(string prefix, int unsigned counts[string],
                                       int unsigned width, dtp_scan_ctrl_expect_e mode,
                                       string context_s);
    string select_id, ctrl_id;
    bit strobes = (mode != DTP_SCAN_CTRL_GATED);
    string ctx = {mode.name(), " ", context_s};
    scan_ctrl_check_ids(prefix, select_id, ctrl_id);
    family_check(select_id, {prefix, "_select asserted"}, 64'(counts[{prefix, "_select"}] > 0),
                 64'(mode == DTP_SCAN_CTRL_SELECTED), ctx);
    family_check(ctrl_id, {prefix, "_capture_en pulses"}, 64'(counts[{prefix, "_capture_en"}]),
                 64'(strobes), ctx);
    family_check(ctrl_id, {prefix, "_shift_en pulses"}, 64'(counts[{prefix, "_shift_en"}]),
                 strobes ? 64'(width) : 64'd0, ctx);
    family_check(ctrl_id, {prefix, "_update_en pulses"}, 64'(counts[{prefix, "_update_en"}]),
                 64'(strobes), ctx);
  endfunction

  // Record that a window the DUT shifted through saw every counted
  // observable stay low.
  function void check_quiet_window(string check_id, int unsigned edges, int unsigned counts[string],
                                   string context_s);
    check_window_shifted(check_id, $sformatf("%s edges=%0d", context_s, edges));
    foreach (counts[name])
    family_check(check_id, {name, " quiet"}, 64'(counts[name]), 64'd0, context_s);
  endfunction

  // Load an instruction and judge its DR scan under a boundary-scan control
  // window. A boundary-scan instruction selects the looped-back chain
  // (CHK-BSR-SELECT, CHK-BSR-LOOPBACK); any other instruction leaves the
  // select low and scans the one-bit bypass register (CHK-BYPASS-DELAY).
  // The TAP's strobes pulse either way (CHK-BSR-SCAN-CTRL). `counts` returns
  // the window counts, including `extra_signals`.
  task check_bsr_scan_ctrl_counts(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                                  input int unsigned width, input dtp_scan_ctrl_expect_e mode,
                                  input string extra_signals[$],
                                  output int unsigned counts[string]);
    string signals[$];
    bit [63:0] observed;
    int unsigned edges;
    string ctx;
    load_ir(instr);
    expect_decoded_instruction(dtp_jtag_instr_e'(instr));
    scan_ctrl_signals(BsrScanCtrl, signals);
    foreach (extra_signals[i]) signals.push_back(extra_signals[i]);
    shift_dr_windowed(pattern, width, signals, observed, edges, counts);
    ctx = $sformatf("ir=0x%02h pattern=0x%0h width=%0d edges=%0d", instr, pattern, width, edges);
    check_scan_ctrl_counts(BsrScanCtrl, counts, width, mode, ctx);
    if (mode == DTP_SCAN_CTRL_SELECTED)
      family_check("CHK-BSR-LOOPBACK", $sformatf("IR 0x%02h loopback", instr), observed & bit_mask(
                   width), (pattern << 1) & bit_mask(width), ctx);
    else check_bypass_tdo(instr, observed, pattern, width, 1'b0, ctx);
  endtask

  task check_bsr_scan_ctrl(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                           input int unsigned width = DtpBsrModelLen,
                           input dtp_scan_ctrl_expect_e mode = DTP_SCAN_CTRL_SELECTED);
    string no_extra[$];
    int unsigned counts[string];
    check_bsr_scan_ctrl_counts(instr, pattern, width, mode, no_extra, counts);
  endtask

  // ------------------------------------------------------------------
  // One-bit bypass family (BYPASS encodings, INV_BYPASS, ZERO_LENGTH).
  // ------------------------------------------------------------------

  // Expected LSB-first TDO for the inverted one-bit bypass register:
  // capture bit 1, then the inverted pattern delayed by one TCK.
  static function bit [63:0] expected_inverted_bypass_tdo(bit [63:0] pattern, int unsigned width);
    bit [63:0] inverted;
    if (width == 0) return '0;
    inverted = (~pattern) & bit_mask(width - 1);
    return 64'h1 | (inverted << 1);
  endfunction

  // CHK-BYPASS-DELAY: the TDO of a one-bit bypass scan is TDI one TCK late.
  function void check_bypass_tdo(bit [IrWidth-1:0] instr, bit [63:0] observed, bit [63:0] pattern,
                                 int unsigned width, bit capture_bit = 1'b0, string context_s = "");
    family_check("CHK-BYPASS-DELAY", $sformatf("bypass TDO for IR 0x%02h", instr),
                 observed & bit_mask(width), ocah_jtag_checker::predict_bypass_tdo(
                 pattern, width, capture_bit), $sformatf(
                 "pattern=0x%0h width=%0d %s", pattern, width, context_s));
  endfunction

  // Load a one-bit bypass instruction, check its decode and 1-TCK
  // TDI-to-TDO latency.
  task check_bypass_delay(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                          input int unsigned width = 64, input bit capture_bit = 1'b0);
    bit [63:0] observed;
    load_ir(instr);
    expect_decoded_instruction(dtp_jtag_instr_e'(instr));
    shift_dr(pattern, width, observed);
    check_bypass_tdo(instr, observed, pattern, width, capture_bit);
  endtask

  // Bypass-delay check with every instruction-qualified host select proven
  // quiet across the scan (CHK-UNDEF-NO-SELECT).
  task check_bypass_no_host_select(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                                   input int unsigned width = 64);
    string selects[$];
    bit [63:0] observed;
    int unsigned edges;
    int unsigned counts[string];
    string ctx;
    load_ir(instr);
    expect_decoded_instruction(dtp_jtag_instr_e'(instr));
    host_selects(selects);
    shift_dr_windowed(pattern, width, selects, observed, edges, counts);
    ctx = $sformatf("ir=0x%02h width=%0d edges=%0d", instr, width, edges);
    check_bypass_tdo(instr, observed, pattern, width, 1'b0, ctx);
    check_quiet_window(NoHostSelectCheckId, edges, counts, ctx);
  endtask

  task check_bypass_patterns(input bit [IrWidth-1:0] instr, input int unsigned width = 64);
    bit [63:0] patterns[$];
    directed_patterns(width, patterns);
    foreach (patterns[p]) check_bypass_delay(instr, patterns[p], width);
  endtask

  // CHK-INV-BYPASS: inverted one-bit bypass delay.
  task check_inverted_bypass_delay(input bit [63:0] pattern, input int unsigned width = 64);
    bit [63:0] observed;
    load_ir(INV_BYPASS_INSTR);
    shift_dr(pattern, width, observed);
    family_check("CHK-INV-BYPASS", "inverted bypass TDO", observed & bit_mask(width),
                 expected_inverted_bypass_tdo(pattern, width), $sformatf(
                 "pattern=0x%0h width=%0d", pattern, width));
  endtask

  task check_inverted_bypass_patterns(input int unsigned width = 64);
    bit [63:0] patterns[$];
    directed_patterns(width, patterns);
    foreach (patterns[p]) check_inverted_bypass_delay(patterns[p], width);
  endtask

  // CHK-ZLB-PASSTHROUGH: zero-length bypass returns TDI directly.
  task check_zero_length_bypass(input bit [63:0] pattern, input int unsigned width = 64);
    bit [63:0] observed;
    load_ir(ZERO_LENGTH_BYPASS_INSTR);
    shift_dr(pattern, width, observed);
    family_check("CHK-ZLB-PASSTHROUGH", "zero-length bypass TDO", observed & bit_mask(width),
                 pattern & bit_mask(width), $sformatf("pattern=0x%0h width=%0d", pattern, width));
  endtask

  task check_zero_length_bypass_patterns(input int unsigned width = 64);
    bit [63:0] patterns[$];
    directed_patterns(width, patterns);
    foreach (patterns[p]) check_zero_length_bypass(patterns[p], width);
  endtask

  // ------------------------------------------------------------------
  // Compact BSR loopback family (SAMPLE/PRELOAD, EXTEST, INTEST, ...).
  // ------------------------------------------------------------------

  // CHK-BSR-LOOPBACK: the looped-back chain returns the pattern retimed by
  // one TCK (dtp_scan_model.py loopback_expected).
  task check_loopback_scan(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                           input int unsigned width = DtpBsrModelLen);
    bit [63:0] observed;
    load_ir(instr);
    expect_decoded_instruction(dtp_jtag_instr_e'(instr));
    shift_dr(pattern, width, observed);
    family_check("CHK-BSR-LOOPBACK", $sformatf("IR 0x%02h loopback", instr), observed & bit_mask(
                 width), (pattern << 1) & bit_mask(width), $sformatf(
                 "pattern=0x%0h width=%0d", pattern, width));
  endtask

  task check_loopback_patterns(input bit [IrWidth-1:0] instr,
                               input int unsigned width = DtpBsrModelLen);
    bit [63:0] patterns[$];
    directed_patterns(width, patterns);
    foreach (patterns[p]) check_loopback_scan(instr, patterns[p], width);
  endtask

  // ------------------------------------------------------------------
  // Random single-operation helpers (cocotb cmd-lib parity).
  // ------------------------------------------------------------------

  task random_bypass_scan(output bit [63:0] pattern, input bit [IrWidth-1:0] instr = BYPASS_INSTR,
                          input int unsigned width = 64);
    pattern = random_pattern(width);
    `uvm_info(get_type_name(), $sformatf("Random BYPASS op instr=0x%02h width=%0d pattern=0x%0h",
                                         instr, width, pattern), UVM_LOW)
    check_bypass_delay(instr, pattern, width);
  endtask

  task random_loopback_scan(output bit [63:0] pattern,
                            input bit [IrWidth-1:0] instr = SAMPLE_PRELOAD_INSTR,
                            input int unsigned width = DtpBsrModelLen);
    pattern = random_pattern(width);
    `uvm_info(get_type_name(), $sformatf("Random loopback op instr=0x%02h width=%0d pattern=0x%0h",
                                         instr, width, pattern), UVM_LOW)
    check_loopback_scan(instr, pattern, width);
  endtask

  // ------------------------------------------------------------------
  // TMP status TDR (CLAMP_HOLD / CLAMP_RELEASE persistence checks).
  // ------------------------------------------------------------------

  // Read TMP_STATUS[1:0]; the default zero shift value catches unwanted
  // R/W side effects (bit 0 arms BYPASS_ESCAPE when written 1).
  task read_tmp_status(output bit persistence, output bit bypass_escape,
                       input bit [1:0] shift_value = 2'b00);
    bit [63:0] observed;
    load_ir(TMP_STATUS_INSTR);
    shift_dr(64'(shift_value), TmpStatusLen, observed);
    persistence   = observed[1];
    bypass_escape = observed[0];
    `uvm_info(get_type_name(), $sformatf("TMP_STATUS raw=0b%02b persistence=%0d bypass_escape=%0d",
                                         observed[1:0], persistence, bypass_escape), UVM_MEDIUM)
  endtask

endclass : dtp_jtag_base_test_seq
