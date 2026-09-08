// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ir_decode reference model: once a plain 6-bit instruction becomes active
// (the TCK cycle leaving Update-IR), the DUT's one-hot decoded-instruction
// observable must equal 1 << instruction. Consumes the JTAG monitor's
// per-TCK event stream (write) and the reconstructed IR scans
// (scan_export) through a dtp_jtag_ir_model, re-baselines on power-on
// reset through dtp_tb_if, and publishes one dtp_expected_item per
// instruction load; the scoreboard samples dtp_tb_if.inst_decoded when the
// item arrives, in the same time step. No comparison, no reporting. The
// cocotb realization has no twin (DTP_TB_ARCH).

`uvm_analysis_imp_decl(_dtp_ir_decode_scan)

class dtp_ir_decode_ref_model extends ocah_ref_model #(ocah_jtag_event, dtp_expected_item);
  `uvm_component_utils(dtp_ir_decode_ref_model)

  // Handed by dtp_env: the power-on reset counter the model re-baselines on.
  virtual dtp_tb_if tb_vif;

  uvm_analysis_imp_dtp_ir_decode_scan #(ocah_jtag_scan_item, dtp_ir_decode_ref_model) scan_export;

  protected dtp_jtag_ir_model m_model;

  function new(string name = "dtp_ir_decode_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    scan_export = new("scan_export", this);
    m_model     = new();
  endfunction

  // Per-TCK events: the instruction commits on the cycle leaving Update-IR.
  function void write(ocah_jtag_event t);
    dtp_expected_item exp;
    void'(m_model.sync_power_on_reset(tb_vif.por_assert_count));
    if (!m_model.on_event(t)) return;
    exp           = dtp_expected_item::type_id::create("exp");
    exp.timestamp = t.timestamp;
    exp.expected  = 64'd1 << m_model.ir();
    exp.mask      = '1;
    exp.context_s = $sformatf("ir=0x%02h load=%0d", m_model.ir(), m_model.ir_loads());
    expected_ap.write(exp);
  endfunction

  // Reconstructed scans: IR scans feed the pending instruction.
  function void write_dtp_ir_decode_scan(ocah_jtag_scan_item t);
    void'(m_model.sync_power_on_reset(tb_vif.por_assert_count));
    if (t.is_ir) m_model.on_ir_scan(t);
  endfunction

endclass : dtp_ir_decode_ref_model
