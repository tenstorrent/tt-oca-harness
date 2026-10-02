// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// debug_control_tdr reference model: the DEBUG_CONTROL TDR captures, on its
// four software-owned bits, the image the previous Update-DR left, and zero
// after any TAP reset (TRST, Test-Logic-Reset, power-on reset: PTAP document
// "Debug Control", every bit resets to 0; the register is in the TCK domain,
// so a cold reset of the SMU leaves it alone). Bit 4 is the captured
// cla_clock_stop status and carries no contract here. Consumes the
// reconstructed scan stream (write) and the per-TCK event stream
// (event_export) through a dtp_jtag_ir_model, keeps the shadow rebuilt from
// the TDI image of every DEBUG_CONTROL DR scan, and publishes one
// smu_tdr_expected_item per scan item. cfg.debug_control_tdr_negative
// (+SMU_DEBUG_CONTROL_SCOREBOARD_NEGATIVE) inverts the predicted boot_stall
// bit so the scoreboard must fail on the first readback. No comparison, no
// reporting. The cocotb twin compares each readback inline
// (smu_boot_stall_jtag_cold_reset_matrix_test.py).

`uvm_analysis_imp_decl(_smu_debug_control_event)

class smu_debug_control_tdr_ref_model
    extends ocah_ref_model #(ocah_jtag_scan_item, smu_tdr_expected_item);
  `uvm_component_utils(smu_debug_control_tdr_ref_model)

  smu_env_cfg       cfg;
  virtual dtp_tb_if dtp_tb_vif;

  uvm_analysis_imp_smu_debug_control_event #(ocah_jtag_event, smu_debug_control_tdr_ref_model)
        event_export;

  protected dtp_env_pkg::dtp_jtag_ir_model m_ir;
  protected bit [SmuDebugControlLen-1:0]   m_tdr;
  protected int unsigned                   m_scans;

  function new(string name = "smu_debug_control_tdr_ref_model", uvm_component parent = null);
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
    m_tdr        = '0;
    if (cfg.debug_control_tdr_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: DEBUG_CONTROL readback predicted with boot_stall inverted",
                UVM_LOW)
  endfunction

  function void write(ocah_jtag_scan_item t);
    smu_tdr_expected_item e = smu_tdr_expected_item::type_id::create("exp");
    e.tdr_name  = "DEBUG_CONTROL";
    e.timestamp = t.end_time;
    sync_power_on_reset();
    if (t.is_ir) begin
      m_ir.on_ir_scan(t);
      expected_ap.write(e);
      return;
    end
    if (m_ir.ir_known() && (m_ir.ir() == dtp_env_pkg::DEBUG_CONTROL_INSTR) &&
            (t.bit_count == SmuDebugControlLen)) begin
      m_scans++;
      e.compare  = 1'b1;
      e.width    = SmuDebugControlLen;
      e.mask     = 256'(SmuDebugControlRwMask);
      e.expected = 256'(m_tdr);
      if (cfg.debug_control_tdr_negative)
        e.expected[SmuDbgBootStallBit] = ~e.expected[SmuDbgBootStallBit];
      e.context_s = $sformatf("DEBUG_CONTROL scan #%0d shadow=0x%02h", m_scans, m_tdr);
      m_tdr = SmuDebugControlLen'(t.tdi_value()) & SmuDebugControlRwMask;
    end
    expected_ap.write(e);
  endfunction

  function void write_smu_debug_control_event(ocah_jtag_event t);
    bit trst = (t.kind == ocah_jtag_uvm_pkg::OCAH_JTAG_EV_TRST) ? t.trst_asserted
                                                                  : (t.trst_n === 1'b0);
    sync_power_on_reset();
    void'(m_ir.on_event(t));
    if (trst || m_ir.take_tap_reset()) m_tdr = '0;
  endfunction

  protected function void sync_power_on_reset();
    if (m_ir.sync_power_on_reset(dtp_tb_vif.por_assert_count)) m_tdr = '0;
  endfunction

endclass : smu_debug_control_tdr_ref_model
