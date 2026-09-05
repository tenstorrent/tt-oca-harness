// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Basic-JTAG family layer of the DTP scenario sequences: the per-pass
// instruction-family evidence checker and the checked operations built on
// the base virtual sequence (dtp_base_test_seq): bypass delay,
// inverted/zero-length bypass, BSR loopback, decoded-IR compare, TMP_STATUS
// reads. Every family helper records named CHK-* evidence through a
// per-pass ocah_jtag_checker instead of bare asserts; finalize_family_checker()
// rejects a pass with zero checks or a missing required ID, and cross-checks
// the env scan builder's pin-level IR/DR reconstruction against the
// sequence's own scan intent (CHK-SCAN-COUNT / CHK-SCAN-IR-LEN /
// CHK-SCAN-DR-LEN / CHK-NONVAC). The basic-JTAG, debug-TDR, and
// scan-network scenarios extend it; the cocotb twins are
// seq_lib/dtp_jtag_base_test_seq.py and seq_lib/dtp_jtag_cmd_lib_seq.py.
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
      scan_builder.clear_history();
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

  // Cross-check the passive scan-builder reconstruction against the
  // sequence's own scan intent, then finalize the per-pass evidence.
  function void finalize_family_checker();
    if (m_family == null) `uvm_fatal(get_type_name(), "family checker was never attached")
    if (m_scan_crosscheck && scan_builder != null) begin
      int unsigned ir_new = scan_builder.ir_items.size() - m_ir_scan_base;
      int unsigned dr_new = scan_builder.dr_items.size() - m_dr_scan_base;
      bit counts_match = (ir_new == m_expected_ir_widths.size()) &&
                               (dr_new == m_expected_dr_widths.size());
      void'(m_family.expect_true(
          "CHK-SCAN-COUNT",
          counts_match,
          $sformatf(
              "monitored (ir=%0d, dr=%0d) vs sequence-issued (ir=%0d, dr=%0d)",
              ir_new,
              dr_new,
              m_expected_ir_widths.size(),
              m_expected_dr_widths.size())
      ));
      if (counts_match) begin
        foreach (m_expected_ir_widths[i])
        void'(m_family.check_scan_length(
            scan_builder.ir_items[m_ir_scan_base+i],
            m_expected_ir_widths[i],
            $sformatf(
                "ir_scan#%0d", i + 1)
        ));
        foreach (m_expected_dr_widths[i])
        void'(m_family.check_scan_length(
            scan_builder.dr_items[m_dr_scan_base+i],
            m_expected_dr_widths[i],
            $sformatf(
                "dr_scan#%0d", i + 1)
        ));
      end
      void'(m_family.expect_true(
          "CHK-NONVAC",
          (ir_new > 0) && (dr_new > 0),
          $sformatf(
              "ir_scans=%0d dr_scans=%0d", ir_new, dr_new)
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
  task reset_to_tlr();
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
  task expect_decoded_instruction(jtag_instruction_e instr);
    family_check("CHK-IR-DECODE", "decoded instruction", 64'(tb_vif.inst_decoded),
                 64'h1 << int'(instr), $sformatf("ir=0x%02h", instr));
  endtask

  // CHK-BSR-SELECT: the boundary-scan chain select observable after an IR
  // load; scenarios assert the VPLAN-expected value for their instruction.
  function void check_bsr_select(bit expected, string context_s);
    family_check("CHK-BSR-SELECT", "jtag_bsr_select", 64'(tb_vif.jtag_bsr_select), 64'(expected),
                 context_s);
  endfunction

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

  // CHK-BYPASS-DELAY: one-bit bypass 1-TCK TDI-to-TDO latency.
  task check_bypass_delay(input bit [IrWidth-1:0] instr, input bit [63:0] pattern,
                          input int unsigned width = 64, input bit capture_bit = 1'b0);
    bit [63:0] observed;
    load_ir(instr);
    shift_dr(pattern, width, observed);
    family_check("CHK-BYPASS-DELAY", $sformatf("bypass TDO for IR 0x%02h", instr),
                 observed & bit_mask(width), ocah_jtag_checker::predict_bypass_tdo(
                 pattern, width, capture_bit), $sformatf("pattern=0x%0h width=%0d", pattern, width
                 ));
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
    expect_decoded_instruction(jtag_instruction_e'(instr));
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
