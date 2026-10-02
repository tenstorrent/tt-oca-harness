// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// bypass reference model: every DR scan of at most 64 bits while a
// bypass-class instruction is active and the PTAP 3DCR select is clear
// returns TDI delayed by one TCK
// (the one-bit bypass register, both IEEE encodings and every undefined
// opcode), INV_BYPASS the inverted delayed image behind a captured 1, and
// ZERO_LENGTH_BYPASS TDI itself. Consumes the reconstructed scan stream
// (write) and the per-TCK event stream (event_export) through a
// dtp_jtag_ir_model, re-baselines on power-on reset through dtp_tb_if, and
// publishes one dtp_expected_item per scan item so the scoreboard pairs
// the two streams in lockstep; scans outside the contract carry none. No
// comparison, no reporting. The cocotb twin is env/dtp_bypass_ref_model.py.

`uvm_analysis_imp_decl(_dtp_bypass_event)

class dtp_bypass_ref_model extends ocah_ref_model #(ocah_jtag_scan_item, dtp_expected_item);
  `uvm_component_utils(dtp_bypass_ref_model)

  virtual dtp_tb_if tb_vif;

  uvm_analysis_imp_dtp_bypass_event #(ocah_jtag_event, dtp_bypass_ref_model) event_export;

  protected dtp_jtag_ir_model m_model;

  function new(string name = "dtp_bypass_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    event_export = new("event_export", this);
    m_model      = new();
  endfunction

  function void write(ocah_jtag_scan_item t);
    dtp_expected_item exp = dtp_expected_item::type_id::create("exp");
    void'(m_model.sync_power_on_reset(tb_vif.por_assert_count));
    exp.timestamp = t.end_time;
    exp.compare   = 1'b0;
    if (t.is_ir) m_model.on_ir_scan(t);
    else begin
      m_model.on_dr_scan(t);
      predict_dr_scan(t, exp);
    end
    expected_ap.write(exp);
  endfunction

  function void write_dtp_bypass_event(ocah_jtag_event t);
    void'(m_model.sync_power_on_reset(tb_vif.por_assert_count));
    void'(m_model.on_event(t));
  endfunction

  protected function void predict_dr_scan(ocah_jtag_scan_item t, dtp_expected_item exp);
    bit [DtpIrWidth-1:0] ir = m_model.ir();
    bit [63:0]           expected;
    if (!m_model.ir_known() || !m_model.ptap_select_clear() || t.bit_count == 0 || t.bit_count > 64)
      return;
    if (is_bypass_instruction(ir))
      expected = ocah_jtag_checker::predict_bypass_tdo(t.tdi_value(), t.bit_count);
    else if (ir == INV_BYPASS_INSTR) expected = inverted_bypass_tdo(t.tdi_value(), t.bit_count);
    else if (ir == ZERO_LENGTH_BYPASS_INSTR) expected = t.tdi_value();
    else return;
    exp.compare   = 1'b1;
    exp.mask      = ocah_rng::bit_mask(t.bit_count);
    exp.expected  = expected & exp.mask;
    exp.context_s = $sformatf("ir=0x%02h bits=%0d", ir, t.bit_count);
  endfunction

  // The one-bit bypass register: both IEEE encodings and every undefined
  // opcode (dtp_jtag_instr_e UNDEFINED_BYPASS_*).
  protected function bit is_bypass_instruction(bit [DtpIrWidth-1:0] ir);
    return (ir == BYPASS_ALT_INSTR) ||
               (ir == BYPASS_INSTR) ||
               (ir == UNDEFINED_BYPASS_0F_INSTR) ||
               (ir >= UNDEFINED_BYPASS_2D_INSTR &&
                ir <= UNDEFINED_BYPASS_3C_INSTR);
  endfunction

  // Inverted one-bit bypass: capture bit 1, then the inverted pattern
  // delayed by one TCK (LSB-first).
  protected function bit [63:0] inverted_bypass_tdo(bit [63:0] pattern, int unsigned width);
    bit [63:0] inverted;
    if (width == 0) return '0;
    inverted = (~pattern) & ocah_rng::bit_mask(width - 1);
    return 64'h1 | (inverted << 1);
  endfunction

endclass : dtp_bypass_ref_model
