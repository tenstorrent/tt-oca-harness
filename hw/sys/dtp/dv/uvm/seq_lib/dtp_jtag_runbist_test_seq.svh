// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_runbist_test scenario sequence. RUNBIST (IR 0x02) selects the
// iJTAG network as its data register: with every SIB closed that register
// is the three-SIB chain and an open SIB splices its instrument stub in, so
// a DR scan returns the chain's capture bits followed by the pattern one TCK
// per chain flop behind TDI (CHK-RUNBIST-DR-LEN), and
// directed plus seeded scans produce distinct, nonzero responses
// (CHK-RUNBIST-RESPONSE). The RUNBIST strobe reaches the non-secure DFT host
// whatever the SIB state and the dft_nonsecure disable (CHK-DFT-RUNBIST);
// that disable holds the DFT SIB closed and silences its host scan controls
// (CHK-DFT-SIB-SELECT, CHK-DFT-SCAN-CTRL) without touching the instruction
// decode. Mirrors the cocotb dtp_jtag_runbist_test_seq.

class dtp_jtag_runbist_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_runbist_test_seq)

  // Wider than the SIB chain, so the retimed pattern is visible above the
  // captures.
  localparam int unsigned RunbistScanWidth = 8;
  localparam string RunbistStrobeCheckId = "CHK-DFT-RUNBIST";
  localparam string RunbistDrCheckId = "CHK-RUNBIST-DR-LEN";

  // Chain state the scans program and the disable vector gating it.
  protected dtp_ijtag_sib_model m_sib_model;
  protected sep_lifecycle_ctrl_pkg::dbg_disable_t m_dbg_disable;

  function new(string name = "dtp_jtag_runbist_test_seq");
    super.new(name);
    m_sib_model = new();
  endfunction

  // Stored SIB bits that open the non-secure DFT SIB alone.
  protected static function void dft_sib_open(output bit bits[DtpIjtagSibCount]);
    bits[IJ_DFT_SECURE] = 1'b0;
    bits[IJ_DFT]        = 1'b1;
    bits[IJ_DFD]        = 1'b0;
  endfunction

  // Load RUNBIST; check its decode and the DFT host's runbist strobe.
  protected task load_runbist(string context_s);
    load_ir(RUNBIST_INSTR);
    expect_decoded_instruction(RUNBIST_INSTR);
    check_scan_observable(RunbistStrobeCheckId, "jtag_dft_runbist", 1'b1, context_s);
  endtask

  // Compare one RUNBIST DR scan with the chain prediction, then commit its
  // update.
  protected function void judge_runbist_tdo(bit [63:0] pattern, bit [63:0] observed,
                                            string context_s);
    bit eff[DtpIjtagSibCount];
    bit [63:0] expected = m_sib_model.expected_scan_tdo(RunbistScanWidth, m_dbg_disable, pattern);
    m_sib_model.effective(m_dbg_disable, eff);
    family_check(RunbistDrCheckId,
                 "RUNBIST TDO is the iJTAG chain: capture bits, then TDI behind the chain",
                 observed, expected, $sformatf(
                 "pattern=0x%02h chain_len=%0d sibs=%p %s",
                 pattern,
                 m_sib_model.chain_len(
                     m_dbg_disable
                 ),
                 eff,
                 context_s
                 ));
    m_sib_model.apply_raw_scan(RunbistScanWidth, m_dbg_disable, pattern);
  endfunction

  // One RUNBIST DR scan judged against the SIB-chain prediction.
  protected task runbist_scan(input bit [63:0] pattern, input string context_s,
                              output bit [7:0] observed);
    bit [63:0] raw;
    shift_dr(pattern, RunbistScanWidth, raw);
    observed = raw[7:0];
    judge_runbist_tdo(pattern, 64'(observed), context_s);
  endtask

  // RUNBIST DR scan under a window on the non-secure DFT host scan controls.
  protected task runbist_scan_windowed(bit [63:0] pattern, dtp_scan_ctrl_expect_e mode,
                                       string context_s);
    string signals[$];
    bit [63:0] observed;
    int unsigned edges;
    int unsigned counts[string];
    scan_ctrl_signals(DftScanCtrl, signals);
    shift_dr_windowed(pattern, RunbistScanWidth, signals, observed, edges, counts);
    judge_runbist_tdo(pattern, observed & bit_mask(RunbistScanWidth), context_s);
    check_scan_ctrl_counts(DftScanCtrl, counts, RunbistScanWidth, mode, $sformatf(
                           "%s edges=%0d", context_s, edges));
  endtask

  // RUNBIST scan value that keeps only the DFT SIB open and randomizes the
  // instrument segment and the bits that fall through the chain.
  protected function bit [63:0] dft_open_pattern();
    bit bits[DtpIjtagSibCount];
    bit [63:0] inst[int];
    bit [63:0] value;
    int unsigned free = RunbistScanWidth - m_sib_model.chain_len(m_dbg_disable);
    dft_sib_open(bits);
    inst[int'(IJ_DFT)] = random_pattern(DtpIjtagInstrumentWidths[IJ_DFT]);
    value = m_sib_model.compose_scan(RunbistScanWidth, m_dbg_disable,
                                     int'(dtp_ijtag_sib_model::pattern_value(bits)), inst);
    if (free > 0) value |= random_pattern(free);
    return value;
  endfunction

  // Program the SIB chain through SELECT_IJTAG so only the DFT SIB is open.
  protected task open_dft_sib();
    bit bits[DtpIjtagSibCount];
    bit [63:0] inst[int];
    bit [63:0] value, unused;
    int unsigned width = m_sib_model.chain_len(m_dbg_disable);
    dft_sib_open(bits);
    value = m_sib_model.compose_scan(width, m_dbg_disable,
                                     int'(dtp_ijtag_sib_model::pattern_value(bits)), inst);
    load_ir(6'(SELECT_IJTAG_INSTR));
    shift_dr(value, width, unused);
    m_sib_model.apply_raw_scan(width, m_dbg_disable, value);
  endtask

  // Directed and seeded RUNBIST scans: chain response, distinct and nonzero.
  protected task check_runbist_response();
    bit [63:0] patterns[$];
    bit seen_results[bit [7:0]];
    bit any_nonzero = 1'b0;
    string results_s = "";
    bit [7:0] observed;
    patterns = {64'h00, 64'hFF, 64'h5A, 64'hA5};
    for (int unsigned r = 0; r < random_count; r++)
      patterns.push_back(random_pattern(RunbistScanWidth));
    foreach (patterns[p]) begin
      runbist_scan(patterns[p], $sformatf("sweep#%0d", p + 1), observed);
      seen_results[observed] = 1'b1;
      if (observed != 8'h0) any_nonzero = 1'b1;
      results_s = {results_s, $sformatf("%s0x%02h", p ? "," : "", observed)};
    end
    family_check("CHK-RUNBIST-RESPONSE", "distinct RUNBIST scan responses",
                 64'(seen_results.num() > 1), 64'h1, $sformatf(
                 "patterns=%0d results=%s", patterns.size(), results_s));
    family_check("CHK-RUNBIST-RESPONSE", "nonzero RUNBIST scan response", 64'(any_nonzero), 64'h1,
                 $sformatf("results=%s", results_s));
  endtask

  task body();
    string required[$] = {
      "CHK-TAP-RESET-TLR",
      "CHK-IR-DECODE",
      "CHK-RUNBIST-RESPONSE",
      RunbistDrCheckId,
      RunbistStrobeCheckId,
      "CHK-DFT-SIB-SELECT",
      "CHK-DFT-SCAN-CTRL",
      "CHK-SCAN-COUNT",
      "CHK-SCAN-IR-LEN",
      "CHK-SCAN-DR-LEN",
      "CHK-NONVAC"
    };
    seed_scenario_rng();
    attach_family_checker(required);
    `uvm_info(get_type_name(),
              "Step 1: Reset TAP; RUNBIST raises the DFT runbist strobe, BYPASS drops it", UVM_LOW)
    reset_to_tlr();
    m_sib_model.reset();
    m_dbg_disable = '0;
    load_runbist("RUNBIST loaded");
    load_ir(6'(BYPASS_INSTR));
    check_scan_observable(RunbistStrobeCheckId, "jtag_dft_runbist", 1'b0, "BYPASS loaded");
    load_runbist("RUNBIST reloaded");

    `uvm_info(get_type_name(),
              "Step 2: RUNBIST DR scans return the chain capture, then the pattern behind it",
              UVM_LOW)
    check_runbist_response();

    `uvm_info(get_type_name(),
              "Step 3: Open the DFT SIB: the RUNBIST scan drives the DFT host scan controls",
              UVM_LOW)
    open_dft_sib();
    load_runbist("RUNBIST with the DFT SIB open");
    runbist_scan_windowed(dft_open_pattern(), DTP_SCAN_CTRL_SELECTED, "dft enabled");

    `uvm_info(get_type_name(),
              "Step 4: dft_nonsecure disable gates the DFT SIB, not the RUNBIST instruction",
              UVM_LOW)
    m_dbg_disable = '0;
    m_dbg_disable.dft_nonsecure = 1'b1;
    set_dbg_disable(m_dbg_disable);
    load_runbist("RUNBIST under the dft_nonsecure disable");
    runbist_scan_windowed(dft_open_pattern(), DTP_SCAN_CTRL_GATED, "dft disabled");

    `uvm_info(get_type_name(),
              "Step 5: Clearing the disable restores the stored DFT SIB open state", UVM_LOW)
    m_dbg_disable = '0;
    set_dbg_disable(m_dbg_disable);
    runbist_scan_windowed(dft_open_pattern(), DTP_SCAN_CTRL_SELECTED, "dft restored");
    finalize_family_checker();
  endtask

endclass : dtp_jtag_runbist_test_seq
