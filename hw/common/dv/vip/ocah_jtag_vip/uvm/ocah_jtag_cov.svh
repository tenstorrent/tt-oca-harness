// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Optional functional-coverage subscriber: samples the shared covergroups in
// cov/ocah_jtag_cov.sv (ocah_jtag_cov_if) from the monitor's per-TCK STEP
// stream (state/transition/reset coverage, tracked through the VIP's TAP
// reference model) and, when a scan reconstruction source is connected to
// scan_export, per reconstructed IR/DR scan. Built by ocah_jtag_master_env only when
// cfg.en_cov is set; the TB instantiates ocah_jtag_cov_if and publishes it as
// "jtag_cov_vif". Commercial-simulator only (never in Verilator filelists),
// like the interface it samples.

`uvm_analysis_imp_decl(_ocah_jtag_scan)

class ocah_jtag_cov extends uvm_subscriber #(ocah_jtag_event);
  `uvm_component_utils(ocah_jtag_cov)

  ocah_jtag_master_config cfg;
  virtual ocah_jtag_cov_if cov_vif;

  // Optional scan-item input (connect a scan builder's scan_ap here).
  uvm_analysis_imp_ocah_jtag_scan #(ocah_jtag_scan_item, ocah_jtag_cov) scan_export;

  protected ocah_jtag_ref_model m_ref;

  function new(string name = "ocah_jtag_cov", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_master_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_master_config `cfg` not found in uvm_config_db")
    if (!uvm_config_db#(virtual ocah_jtag_cov_if)::get(
            this, "", "jtag_cov_vif", cov_vif
        ) || cov_vif == null)
      `uvm_fatal(get_type_name(), "virtual ocah_jtag_cov_if `jtag_cov_vif` not found")
    scan_export = new("scan_export", this);
    m_ref = ocah_jtag_ref_model::type_id::create("m_ref");
  endfunction

  function void write(ocah_jtag_event t);
    ocah_jtag_tap_state_e previous;
    ocah_jtag_tap_state_e next;

    if (t.kind == OCAH_JTAG_EV_TRST) begin
      if (t.trst_asserted) begin
        m_ref.reset_model();
        cov_vif.sample_reset(1'b1);
      end
      return;
    end
    if (t.trst_n === 1'b0) begin
      m_ref.reset_model();
      return;
    end

    previous = m_ref.state();
    next     = m_ref.step(t.tms);
    cov_vif.sample_step(int'(previous), t.tms, int'(next));
    if (next == OCAH_JTAG_TEST_LOGIC_RESET && previous != OCAH_JTAG_TEST_LOGIC_RESET)
      cov_vif.sample_reset(1'b0);
  endfunction

  function void write_ocah_jtag_scan(ocah_jtag_scan_item t);
    cov_vif.sample_scan(t.is_ir, t.bit_count, t.instruction_known, 6'(t.instruction));
  endfunction

endclass : ocah_jtag_cov
