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
// (IEEE 1149.1 6.1.1). Plain class held by the JTAG reference models
// (ir_decode, idcode, bypass, jtag2axi); no reporting. The cocotb twin is
// the TAP tracking in env/dtp_tap_device.py.

class dtp_jtag_ir_model;

  protected ocah_jtag_tap_state_e m_tap = OCAH_JTAG_TEST_LOGIC_RESET;
  protected bit                   m_ir_known = 1'b1;
  protected bit [DtpIrWidth-1:0]  m_ir = jtag_inst_reg_pkg::IDCODE_INSTR;
  protected bit                   m_pending_ir_valid;
  protected bit [DtpIrWidth-1:0]  m_pending_ir;
  protected int unsigned          m_pending_ir_scans;
  protected int unsigned          m_ir_loads;
  protected bit [31:0]            m_por_seen;
  protected bit                   m_tap_reset_seen;

  function new();
    reset_tap();
  endfunction

  // One completed TCK cycle or a TRST edge. Returns 1 when an instruction
  // became active on this event (the cycle leaving Update-IR).
  function bit on_event(ocah_jtag_event t);
    bit committed = 1'b0;
    if (t.kind == OCAH_JTAG_EV_TRST) begin
      if (t.trst_asserted) reset_tap();
      return 1'b0;
    end
    if (t.trst_n === 1'b0) begin
      reset_tap();
      return 1'b0;
    end
    if (m_tap == OCAH_JTAG_UPDATE_IR) committed = commit_instruction();
    m_tap = ocah_jtag_next_state(m_tap, t.tms);
    if (m_tap == OCAH_JTAG_TEST_LOGIC_RESET) reset_tap();
    return committed;
  endfunction

  // One reconstructed IR scan (published on Shift-IR -> Exit1-IR).
  function void on_ir_scan(ocah_jtag_scan_item t);
    m_pending_ir_scans++;
    m_pending_ir_valid = (t.bit_count == DtpIrWidth);
    m_pending_ir       = DtpIrWidth'(t.tdi_value());
  endfunction

  // Power-on reset resets the TAP; the tb_if assertion counter is the
  // observable. Returns 1 when a new assertion was seen.
  function bit sync_power_on_reset(bit [31:0] por_assert_count);
    if (por_assert_count === m_por_seen) return 1'b0;
    m_por_seen = por_assert_count;
    reset_tap();
    return 1'b1;
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
    m_ir               = jtag_inst_reg_pkg::IDCODE_INSTR;
    m_ir_known         = 1'b1;
    m_pending_ir_valid = 1'b0;
    m_pending_ir_scans = 0;
    m_tap_reset_seen   = 1'b1;
  endfunction

  // The value the instruction shift register holds on the cycle leaving
  // Update-IR: the Capture-IR pattern when no Shift-IR cycle followed the
  // capture, the scanned opcode after one plain 6-bit scan, unknown
  // otherwise.
  protected function bit commit_instruction();
    bit [DtpIrWidth-1:0] latched;
    bit known = 1'b1;
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
