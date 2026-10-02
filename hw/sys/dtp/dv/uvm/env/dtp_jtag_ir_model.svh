// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Primary-TAP instruction model: the TAP state and the active instruction
// of the DTP PTAP, rebuilt from the JTAG monitor's per-TCK events and the
// reconstructed IR scans. Update-IR latches the instruction shift register:
// after one plain 6-bit IR scan that is the scanned opcode; after an IR scan
// that reaches Update-IR without a Shift-IR cycle it is the Capture-IR
// pattern (DtpIrCapturePattern, the IDCODE opcode); a composed scan (wider,
// spanning the STAP chain) or a re-shifted instruction scan leaves it
// unknown until the next plain load or TAP reset. Test-Logic-Reset by TRST
// or TMS, and power-on reset, load the device-identification instruction
// (IEEE 1149.1 6.1.1).
//
// The model also tracks the PTAP 3DCR, {stap_sel, config_hold}. The 3DCR
// takes TDI directly, so Update-DR under TAP_3DCR latches the last two bits
// the scan shifted in, or the shifted bit and the old stap_sel after a
// one-bit scan. Test-Logic-Reset by TMS clears it unless config_hold is set;
// TRST and power-on reset always clear it. Whether a data scan ran under
// TAP_3DCR is decided from the instruction register's shifted value, which
// stays known through composed and re-shifted instruction scans. While the
// select is set the PTAP splices the STAP chain onto the TDO end of every
// data scan, so a model that predicts TDO carries no contract unless
// ptap_select_clear() holds.
//
// Plain class held by the JTAG reference models (ir_decode, idcode, bypass,
// jtag2axi); no reporting. The cocotb twin is the TAP tracking in
// env/dtp_tap_device.py.

class dtp_jtag_ir_model;

  protected ocah_jtag_tap_state_e m_tap = OCAH_JTAG_TEST_LOGIC_RESET;
  protected bit                   m_ir_known = 1'b1;
  protected bit [DtpIrWidth-1:0]  m_ir = IDCODE_INSTR;
  protected bit                   m_pending_ir_valid;
  protected bit [DtpIrWidth-1:0]  m_pending_ir;
  protected int unsigned          m_pending_ir_scans;
  protected int unsigned          m_ir_loads;
  protected bit [31:0]            m_por_seen;
  protected bit                   m_tap_reset_seen;
  // The instruction register's value after the last Update-IR or reset. The
  // PTAP IR is the TDI-nearest segment of every instruction scan, so it
  // holds the last six bits shifted in, or for a shorter scan the shifted
  // bits above the rest of the Capture-IR pattern.
  protected bit [DtpIrWidth-1:0]  m_shift_ir = IDCODE_INSTR;
  protected bit                   m_ptap_select;
  protected bit                   m_ptap_config_hold;
  // The newest scan item of each kind since the last Update-x; a scan
  // resumed through Pause-x publishes a cumulative item at each Exit1-x.
  protected ocah_jtag_scan_item   m_pending_ir_item;
  protected ocah_jtag_scan_item   m_pending_dr_item;

  function new();
    reset_tap();
  endfunction

  // One completed TCK cycle or a TRST edge. Returns 1 when an instruction
  // became active on this event (the cycle leaving Update-IR).
  function bit on_event(ocah_jtag_event t);
    bit committed = 1'b0;
    if (t.kind == OCAH_JTAG_EV_TRST) begin
      if (t.trst_asserted) hard_reset();
      return 1'b0;
    end
    if (t.trst_n === 1'b0) begin
      hard_reset();
      return 1'b0;
    end
    if (m_tap == OCAH_JTAG_UPDATE_IR) committed = commit_instruction();
    if (m_tap == OCAH_JTAG_UPDATE_DR) commit_data_scan();
    m_tap = ocah_jtag_next_state(m_tap, t.tms);
    if (m_tap == OCAH_JTAG_TEST_LOGIC_RESET) begin
      reset_tap();
      if (!m_ptap_config_hold) m_ptap_select = 1'b0;
    end
    return committed;
  endfunction

  // One reconstructed IR scan (published on Shift-IR -> Exit1-IR).
  function void on_ir_scan(ocah_jtag_scan_item t);
    m_pending_ir_scans++;
    m_pending_ir_valid = (t.bit_count == DtpIrWidth);
    m_pending_ir       = DtpIrWidth'(t.tdi_value());
    m_pending_ir_item  = t;
  endfunction

  // One reconstructed DR scan (published on Shift-DR -> Exit1-DR).
  function void on_dr_scan(ocah_jtag_scan_item t);
    m_pending_dr_item = t;
  endfunction

  // Power-on reset resets the TAP; the tb_if assertion counter is the
  // observable. Returns 1 when a new assertion was seen.
  function bit sync_power_on_reset(bit [31:0] por_assert_count);
    if (por_assert_count === m_por_seen) return 1'b0;
    m_por_seen = por_assert_count;
    hard_reset();
    return 1'b1;
  endfunction

  // True while the PTAP 3DCR select is clear, so a data scan covers the PTAP
  // data register alone.
  function bit ptap_select_clear();
    return !m_ptap_select;
  endfunction

  // Set by every TAP reset (TRST, TMS Test-Logic-Reset, power-on) and
  // cleared by the caller that consumed it.
  function bit take_tap_reset();
    bit seen = m_tap_reset_seen;
    m_tap_reset_seen = 1'b0;
    return seen;
  endfunction

  function bit ir_known();
    return m_ir_known;
  endfunction

  function bit [DtpIrWidth-1:0] ir();
    return m_ir;
  endfunction

  function int unsigned ir_loads();
    return m_ir_loads;
  endfunction

  function ocah_jtag_tap_state_e tap_state();
    return m_tap;
  endfunction

  function void reset_tap();
    m_tap              = OCAH_JTAG_TEST_LOGIC_RESET;
    m_ir               = IDCODE_INSTR;
    m_ir_known         = 1'b1;
    m_shift_ir         = IDCODE_INSTR;
    m_pending_ir_valid = 1'b0;
    m_pending_ir_scans = 0;
    m_pending_ir_item  = null;
    m_pending_dr_item  = null;
    m_tap_reset_seen   = 1'b1;
  endfunction

  // TRST and power-on reset: the TAP reset plus a 3DCR clear that
  // config_hold cannot block.
  protected function void hard_reset();
    reset_tap();
    m_ptap_select      = 1'b0;
    m_ptap_config_hold = 1'b0;
  endfunction

  // Update-DR: a TAP_3DCR scan that shifted at least one bit latches the
  // 3DCR. A capture that reaches Update-DR without a Shift-DR cycle writes
  // back the captured value.
  protected function void commit_data_scan();
    int unsigned n = (m_pending_dr_item != null) ? m_pending_dr_item.bit_count : 0;
    if (m_shift_ir == TAP_3DCR_INSTR && n != 0) begin
      m_ptap_config_hold = (n >= 2) ? m_pending_dr_item.tdi_bits[n-2] : m_ptap_select;
      m_ptap_select      = m_pending_dr_item.tdi_bits[n-1];
    end
    m_pending_dr_item = null;
  endfunction

  // The value the instruction shift register holds on the cycle leaving
  // Update-IR: the Capture-IR pattern when no Shift-IR cycle followed the
  // capture, the scanned opcode after one plain 6-bit scan, unknown
  // otherwise. m_shift_ir follows every scan.
  protected function bit commit_instruction();
    bit [DtpIrWidth-1:0] latched;
    bit known = 1'b1;
    m_shift_ir = DtpIrCapturePattern;
    if (m_pending_ir_item != null)
      foreach (m_pending_ir_item.tdi_bits[i])
      m_shift_ir = {m_pending_ir_item.tdi_bits[i], m_shift_ir[DtpIrWidth-1:1]};
    m_pending_ir_item = null;
    if (m_pending_ir_scans == 0) latched = DtpIrCapturePattern;
    else if (m_pending_ir_scans == 1 && m_pending_ir_valid) latched = m_pending_ir;
    else known = 1'b0;
    m_pending_ir_valid = 1'b0;
    m_pending_ir_scans = 0;
    m_ir_known         = known;
    if (!known) return 1'b0;
    m_ir = latched;
    m_ir_loads++;
    return 1'b1;
  endfunction

endclass : dtp_jtag_ir_model
