// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP scoreboard: always on, in every test, fed only by VIP monitor streams
// and dtp_tb_if observables; one predictor and one comparison counter per
// feature. Expected values come from the DUT collateral and the stimulus
// the monitors saw, never from the observation under check.
//
//   ir_decode  every plain 6-bit IR scan: once the instruction becomes
//              active (the TCK cycle leaving Update-IR), the one-hot
//              decoded-instruction observable must equal 1 << instruction.
//   idcode     every DR scan while IDCODE is the active instruction (after
//              Test-Logic-Reset by TRST or TMS, or an explicit load): the
//              shifted-out low 32 bits must equal the public DTP device
//              identification.
//   bypass     every DR scan of at most 64 bits while a bypass-class
//              instruction is active: the one-bit bypass returns TDI delayed
//              by one TCK, INV_BYPASS the inverted delayed image behind a
//              captured 1, ZERO_LENGTH_BYPASS TDI itself.
//   xtrig_csr  every OKAY read of a cross-trigger CSR with a readback
//              contract (CTM selects, CTP CONFIG and STRETCH_MULT): the data
//              must equal a shadow rebuilt from the writes the passive
//              monitor observed, cleared on every system or power-on reset
//              (tb_if reset counters).
//   xtrig_decode  every access to the unmapped cross-trigger address space
//              must complete with DECERR.
//
// Composed scans (a wider IR scan spanning the STAP chain, or a DR scan
// after one) make the PTAP instruction unrecoverable at this level, so the
// JTAG predictors stand down until the next plain IR load or TAP reset.
// STATUS reads carry no data contract and are skipped.
// The cocotb twin is env/dtp_scoreboard.py.

`uvm_analysis_imp_decl(_dtp_jtag_event)
`uvm_analysis_imp_decl(_dtp_jtag_scan)
`uvm_analysis_imp_decl(_dtp_xtrig_axi)

class dtp_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(dtp_scoreboard)

  dtp_env_cfg cfg;
  // Handed by dtp_env: the decoded-instruction observable and the reset
  // assertion counters the predictors re-baseline on.
  virtual dtp_tb_if tb_vif;

  uvm_analysis_imp_dtp_jtag_event #(ocah_jtag_event, dtp_scoreboard)     jtag_export;
  uvm_analysis_imp_dtp_jtag_scan  #(ocah_jtag_scan_item, dtp_scoreboard) scan_export;
  uvm_analysis_imp_dtp_xtrig_axi  #(ocah_axi_item, dtp_scoreboard)       xtrig_export;

  // JTAG predictor: tracked TAP state, active and pending instruction.
  protected ocah_jtag_tap_state_e   m_tap = OCAH_JTAG_TEST_LOGIC_RESET;
  protected bit                     m_ir_known = 1'b1;
  protected bit [DtpIrWidth-1:0]    m_ir = jtag_inst_reg_pkg::IDCODE_INSTR;
  protected bit                     m_pending_ir_valid;
  protected bit [DtpIrWidth-1:0]    m_pending_ir;
  protected int unsigned            m_pending_ir_scans;
  protected int unsigned            m_ir_loads;
  protected bit [31:0]              m_por_seen;

  // XTRIG predictor: CSR shadow keyed by address, cleared on reset.
  protected bit [31:0] m_csr_shadow[bit [63:0]];
  protected bit [31:0] m_sys_rst_seen;

  function new(string name = "dtp_scoreboard", uvm_component parent = null);
    super.new(name, parent);
    name_tag = "dtp_scoreboard";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(dtp_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "dtp_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    jtag_export  = new("jtag_export", this);
    scan_export  = new("scan_export", this);
    xtrig_export = new("xtrig_export", this);
    add_feature(DtpFeatureIrDecode);
    add_feature(DtpFeatureIdcode);
    add_feature(DtpFeatureBypass);
    add_feature(DtpFeatureXtrigCsr);
    add_feature(DtpFeatureXtrigDecode);
    foreach (cfg.required_features[i]) require_feature(cfg.required_features[i]);
  endfunction

  // ------------------------------------------------------------------
  // JTAG streams.
  // ------------------------------------------------------------------

  // Per-TCK events (falling edge, transition settled): track the TAP
  // state and commit the pending instruction when Update-IR is left.
  function void write_dtp_jtag_event(ocah_jtag_event t);
    sync_power_on_reset();
    if (t.kind == OCAH_JTAG_EV_TRST) begin
      if (t.trst_asserted) reset_tap_predictor();
      return;
    end
    if (t.trst_n === 1'b0) begin
      reset_tap_predictor();
      return;
    end
    if (m_tap == OCAH_JTAG_UPDATE_IR) commit_instruction();
    m_tap = ocah_jtag_next_state(m_tap, t.tms);
    // Test-Logic-Reset (by TMS as well as by TRST) loads the IR with the
    // device-identification instruction (IEEE 1149.1 6.1.1).
    if (m_tap == OCAH_JTAG_TEST_LOGIC_RESET) reset_tap_predictor();
  endfunction

  // Reconstructed scans (published on Shift-x -> Exit1-x).
  function void write_dtp_jtag_scan(ocah_jtag_scan_item t);
    sync_power_on_reset();
    if (t.is_ir) begin
      m_pending_ir_scans++;
      m_pending_ir_valid = (t.bit_count == DtpIrWidth);
      m_pending_ir       = t.tdi_value();
      return;
    end
    predict_dr_scan(t);
  endfunction

  // The instruction latched at Update-IR is the last plain 6-bit IR scan;
  // a composed or re-shifted instruction scan leaves it unknown.
  protected function void commit_instruction();
    if (m_pending_ir_scans == 1 && m_pending_ir_valid) begin
      m_ir       = m_pending_ir;
      m_ir_known = 1'b1;
      m_ir_loads++;
      void'(compare_equal(
          DtpFeatureIrDecode,
          64'(tb_vif.inst_decoded),
          64'd1 << m_ir,
          $sformatf(
              "ir=0x%02h load=%0d", m_ir, m_ir_loads)
      ));
    end else if (m_pending_ir_scans != 0) m_ir_known = 1'b0;
    m_pending_ir_valid = 1'b0;
    m_pending_ir_scans = 0;
  endfunction

  protected function void predict_dr_scan(ocah_jtag_scan_item t);
    bit [63:0] mask, observed, expected;
    string context_s = $sformatf("ir=0x%02h bits=%0d", m_ir, t.bit_count);
    if (!m_ir_known || t.bit_count == 0) return;
    if (m_ir == jtag_inst_reg_pkg::IDCODE_INSTR) begin
      mask = bit_mask((t.bit_count < 32) ? t.bit_count : 32);
      void'(compare_equal(
          DtpFeatureIdcode, t.tdo_value() & mask, DtpDefaultIdcode & mask, context_s
      ));
      return;
    end
    if (t.bit_count > 64) return;
    mask     = bit_mask(t.bit_count);
    observed = t.tdo_value() & mask;
    if (is_bypass_instruction(m_ir))
      expected = ocah_jtag_checker::predict_bypass_tdo(t.tdi_value(), t.bit_count);
    else if (m_ir == jtag_inst_reg_pkg::INV_BYPASS_INSTR)
      expected = inverted_bypass_tdo(t.tdi_value(), t.bit_count);
    else if (m_ir == jtag_inst_reg_pkg::ZERO_LENGTH_BYPASS_INSTR) expected = t.tdi_value();
    else return;
    void'(compare_equal(DtpFeatureBypass, observed, expected & mask, context_s));
  endfunction

  // The one-bit bypass register: both IEEE encodings and every undefined
  // opcode (jtag_inst_reg_pkg UNDEFINED_BYPASS_*).
  protected function bit is_bypass_instruction(bit [DtpIrWidth-1:0] ir);
    return (ir == jtag_inst_reg_pkg::BYPASS_ALT_INSTR) ||
               (ir == jtag_inst_reg_pkg::BYPASS_INSTR) ||
               (ir == jtag_inst_reg_pkg::UNDEFINED_BYPASS_0F_INSTR) ||
               (ir >= jtag_inst_reg_pkg::UNDEFINED_BYPASS_2D_INSTR &&
                ir <= jtag_inst_reg_pkg::UNDEFINED_BYPASS_3C_INSTR);
  endfunction

  // Inverted one-bit bypass: capture bit 1, then the inverted pattern
  // delayed by one TCK (LSB-first).
  protected function bit [63:0] inverted_bypass_tdo(bit [63:0] pattern, int unsigned width);
    bit [63:0] inverted;
    if (width == 0) return '0;
    inverted = (~pattern) & bit_mask(width - 1);
    return 64'h1 | (inverted << 1);
  endfunction

  protected function void reset_tap_predictor();
    m_tap              = OCAH_JTAG_TEST_LOGIC_RESET;
    m_ir               = jtag_inst_reg_pkg::IDCODE_INSTR;
    m_ir_known         = 1'b1;
    m_pending_ir_valid = 1'b0;
    m_pending_ir_scans = 0;
  endfunction

  // Power-on reset resets the TAP (instruction back to IDCODE) and every
  // CSR; the counter on tb_if is the observable.
  protected function void sync_power_on_reset();
    if (tb_vif.por_assert_count === m_por_seen) return;
    m_por_seen = tb_vif.por_assert_count;
    reset_tap_predictor();
    m_csr_shadow.delete();
  endfunction

  // ------------------------------------------------------------------
  // Cross-trigger CSR stream (passive AXI-Lite monitor on the XTRIG port).
  // ------------------------------------------------------------------

  function void write_dtp_xtrig_axi(ocah_axi_item t);
    dtp_xtrig_csr_kind_e kind;
    bit [31:0] mask, shadow, observed;
    sync_power_on_reset();
    if (tb_vif.sys_rst_assert_count !== m_sys_rst_seen) begin
      m_sys_rst_seen = tb_vif.sys_rst_assert_count;
      m_csr_shadow.delete();
    end
    kind = dtp_xtrig_csr_decode(t.address, mask);
    if (kind == DTP_XTRIG_CSR_UNMAPPED) begin
      void'(compare_equal(
          DtpFeatureXtrigDecode,
          64'(t.worst_resp()),
          64'(OCAH_AXI_RESP_DECERR),
          $sformatf(
              "%s addr=0x%03h", t.direction.name(), t.address)
      ));
      return;
    end
    if (kind == DTP_XTRIG_CSR_CTP_STATUS) return;
    if (!t.is_ok() || t.data_words.size() == 0) return;
    shadow = m_csr_shadow.exists(t.address) ? m_csr_shadow[t.address] : '0;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      bit [7:0] strb = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
      m_csr_shadow[t.address] = dtp_xtrig_apply_wstrb(shadow, t.data_words[0][31:0], strb[3:0]) &
          mask;
      return;
    end
    observed = t.data_words[0][31:0] & mask;
    void'(compare_equal(
        DtpFeatureXtrigCsr,
        64'(observed),
        64'(shadow & mask),
        $sformatf(
            "%s addr=0x%03h", kind.name(), t.address)
    ));
  endfunction

  static function bit [63:0] bit_mask(int unsigned width);
    return ocah_rng::bit_mask(width);
  endfunction

endclass : dtp_scoreboard
