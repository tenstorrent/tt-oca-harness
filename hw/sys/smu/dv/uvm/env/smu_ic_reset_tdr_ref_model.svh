// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// ic_reset_tdr reference model: the IC_RESET TDR captures the register image
// the previous Update-DR left, the reset image after TRST or power-on reset,
// and after a Test-Logic-Reset the reset image only while reset_hold is 1
// (PTAP document "IC_RESET Support": reset_hold = 0 keeps the
// reset_enable/reset_control bits across TLR; TRST/POR always reset all
// bits). Consumes the reconstructed scan stream (write) and the per-TCK
// event stream (event_export) through a dtp_jtag_ir_model to know the
// active instruction, keeps the register shadow rebuilt from the TDI image
// of every IC_RESET DR scan, and publishes one smu_tdr_expected_item per
// scan item: the predicted capture for a full-length IC_RESET scan, no
// contract otherwise. cfg.ic_reset_tdr_negative
// (+SMU_IC_RESET_SCOREBOARD_NEGATIVE) inverts the predicted reset_hold bit
// so the scoreboard must fail on the first IC_RESET readback. No comparison,
// no reporting. The cocotb twin compares each readback inline
// (smu_jtag_reset_override_test.py).

`uvm_analysis_imp_decl(_smu_ic_reset_event)

class smu_ic_reset_tdr_ref_model
    extends ocah_ref_model #(ocah_jtag_scan_item, smu_tdr_expected_item);
  `uvm_component_utils(smu_ic_reset_tdr_ref_model)

  smu_env_cfg       cfg;
  virtual dtp_tb_if dtp_tb_vif;

  uvm_analysis_imp_smu_ic_reset_event #(ocah_jtag_event, smu_ic_reset_tdr_ref_model) event_export;

  protected dtp_env_pkg::dtp_jtag_ir_model m_ir;
  protected smu_ic_reset_image_t           m_tdr;
  protected int unsigned                   m_scans;

  function new(string name = "smu_ic_reset_tdr_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smu_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smu_env_cfg `env_cfg` not found in uvm_config_db")
    if (dtp_tb_vif == null)
      `uvm_fatal(get_type_name(), "virtual dtp_tb_if `dtp_tb_vif` not set by the env")
    event_export = new("event_export", this);
    m_ir         = new();
    m_tdr        = SmuIcResetDefault;
    if (cfg.ic_reset_tdr_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: IC_RESET readback predicted with reset_hold inverted",
                UVM_LOW)
  endfunction

  // One expected item per scan: the capture predicted before this scan's
  // own Update-DR is applied to the shadow.
  function void write(ocah_jtag_scan_item t);
    smu_tdr_expected_item e = smu_tdr_expected_item::type_id::create("exp");
    e.tdr_name  = "IC_RESET";
    e.timestamp = t.end_time;
    sync_power_on_reset();
    if (t.is_ir) begin
      m_ir.on_ir_scan(t);
      expected_ap.write(e);
      return;
    end
    if (m_ir.ir_known() && (m_ir.ir() == dtp_env_pkg::IC_RESET_INSTR) &&
            (t.bit_count == SmuIcResetLen)) begin
      m_scans++;
      e.compare  = 1'b1;
      e.width    = SmuIcResetLen;
      e.mask     = 256'((smu_ic_reset_image_t'('1)));
      e.expected = 256'(m_tdr);
      if (cfg.ic_reset_tdr_negative) e.expected[0] = ~e.expected[0];
      e.context_s = $sformatf("IC_RESET scan #%0d shadow=0x%0h", m_scans, m_tdr);
      // Update-DR: the shifted-in image becomes the register.
      m_tdr = smu_ic_reset_image_t'(bits_to_image(t.tdi_bits));
    end
    expected_ap.write(e);
  endfunction

  // Per-TCK events: a TRST assertion restores the reset image; a
  // Test-Logic-Reset entry restores the enable/control bits only under
  // reset_hold = 1.
  function void write_smu_ic_reset_event(ocah_jtag_event t);
    bit trst = (t.kind == ocah_jtag_uvm_pkg::OCAH_JTAG_EV_TRST) ? t.trst_asserted
                                                                  : (t.trst_n === 1'b0);
    sync_power_on_reset();
    void'(m_ir.on_event(t));
    if (trst) m_tdr = SmuIcResetDefault;
    else if (m_ir.take_tap_reset()) apply_tlr();
  endfunction

  protected function void apply_tlr();
    if (m_tdr[0]) m_tdr = SmuIcResetDefault;
  endfunction

  protected function void sync_power_on_reset();
    if (m_ir.sync_power_on_reset(dtp_tb_vif.por_assert_count)) m_tdr = SmuIcResetDefault;
  endfunction

  protected function bit [255:0] bits_to_image(ref bit bits[$]);
    bit [255:0] v = '0;
    foreach (bits[i]) if (i < 256) v[i] = bits[i];
    return v;
  endfunction

endclass : smu_ic_reset_tdr_ref_model
