// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// idcode reference model: every DR scan while IDCODE is the active
// instruction (after Test-Logic-Reset by TRST or TMS, or an explicit load)
// shifts out the DTP device identification (DtpDefaultIdcode) in its low
// 32 bits.
// Consumes the reconstructed scan stream (write) and the per-TCK event
// stream (event_export) through a dtp_jtag_ir_model, re-baselines on
// power-on reset through dtp_tb_if, and publishes one dtp_expected_item
// per scan item so the scoreboard pairs the two streams in lockstep: IR
// scans, scans under another instruction, scans under an unknown
// instruction, and scans while the PTAP 3DCR select is set, when the STAP
// chain follows the identification register, carry no contract.
// No comparison, no reporting. The cocotb twin is
// env/dtp_idcode_ref_model.py.
//
// expected_idcode defaults to DtpDefaultIdcode, the IDCODE tb_top
// elaborates the DUT with (dtp_dv_cfg_pkg); a bench that embeds DTP, such as
// the SMU bench, sets it from its own configuration before build_phase.

`uvm_analysis_imp_decl(_dtp_idcode_event)

class dtp_idcode_ref_model extends ocah_ref_model #(ocah_jtag_scan_item, dtp_expected_item);
  `uvm_component_utils(dtp_idcode_ref_model)

  virtual dtp_tb_if tb_vif;

  // Device identification the model predicts (32 bits, IEEE 1149.1 layout).
  bit [31:0] expected_idcode = DtpDefaultIdcode;

  uvm_analysis_imp_dtp_idcode_event #(ocah_jtag_event, dtp_idcode_ref_model) event_export;

  protected dtp_jtag_ir_model m_model;

  function new(string name = "dtp_idcode_ref_model", uvm_component parent = null);
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
      if (m_model.ir_known() && (t.bit_count != 0) && (m_model.ir() == IDCODE_INSTR) &&
          m_model.ptap_select_clear()) begin
        int unsigned width = (t.bit_count < 32) ? t.bit_count : 32;
        exp.compare   = 1'b1;
        exp.mask      = ocah_rng::bit_mask(width);
        exp.expected  = expected_idcode & exp.mask;
        exp.context_s = $sformatf("ir=0x%02h bits=%0d", m_model.ir(), t.bit_count);
      end
    end
    expected_ap.write(exp);
  endfunction

  function void write_dtp_idcode_event(ocah_jtag_event t);
    void'(m_model.sync_power_on_reset(tb_vif.por_assert_count));
    void'(m_model.on_event(t));
  endfunction

endclass : dtp_idcode_ref_model
