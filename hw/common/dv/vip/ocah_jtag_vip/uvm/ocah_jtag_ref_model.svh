// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// IEEE 1149.1 TAP controller reference model — the SV analogue of the cocotb
// OcahJtagTapRefModel. Tracks the predicted controller state across TMS steps
// and predicts the data behavior of the mandatory BYPASS register. Holds no
// simulator handles; ocah_jtag_checker owns one and DUT-side components may
// share it.
//
// Rule provenance: all TAP contracts are implemented from the public IEEE
// Std 1149.1 clause descriptions. No third-party protocol-checker source was
// consulted or copied.

class ocah_jtag_ref_model extends uvm_object;
  `uvm_object_utils(ocah_jtag_ref_model)

  protected ocah_jtag_tap_state_e m_model = OCAH_JTAG_TEST_LOGIC_RESET;

  function new(string name = "ocah_jtag_ref_model");
    super.new(name);
  endfunction

  function ocah_jtag_tap_state_e state();
    return m_model;
  endfunction

  // Model a TAP reset (TRST assertion or a TMS-high walk) to TLR.
  function void reset_model();
    m_model = OCAH_JTAG_TEST_LOGIC_RESET;
  endfunction

  // Re-align the model after driver-internal navigation (e.g. the scan
  // legs that return to Run-Test/Idle without per-step visibility).
  function void sync_state(ocah_jtag_tap_state_e s);
    m_model = s;
  endfunction

  // Advance one rising TCK edge with the sampled TMS bit.
  function ocah_jtag_tap_state_e step(bit tms);
    m_model = ocah_jtag_next_state(m_model, tms);
    return m_model;
  endfunction

  // Expected LSB-first TDO for a scan through the one-bit BYPASS register:
  // bit 0 is the captured bit, bits [width-1:1] the first width-1 pattern
  // bits (exactly one TCK of TDI-to-TDO delay).
  static function bit [63:0] predict_bypass_tdo(bit [63:0] pattern, int unsigned width,
                                                bit capture_bit = 1'b0);
    bit [63:0] mask;
    if (width == 0) return '0;
    mask = (width < 64) ? ((64'h1 << width) - 1) : '1;
    return (({pattern[62:0], capture_bit}) & mask);
  endfunction

  // One-hot helpers for the exported-observable form (bit index == the
  // enum's IEEE state number).
  static function bit onehot_to_state(bit [15:0] onehot, output ocah_jtag_tap_state_e s);
    if ($countones(onehot) != 1) return 1'b0;
    for (int i = 0; i < 16; i++) begin
      if (onehot[i]) begin
        s = ocah_jtag_tap_state_e'(i);
        return 1'b1;
      end
    end
    return 1'b0;
  endfunction

  static function string onehot_label(bit [15:0] onehot);
    ocah_jtag_tap_state_e s;
    if (onehot_to_state(onehot, s)) return $sformatf("%s(0x%04h)", s.name(), onehot);
    return $sformatf("INVALID(0x%04h)", onehot);
  endfunction

endclass : ocah_jtag_ref_model
