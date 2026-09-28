// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// jtag2axi_req reference model: every AXI transaction a JTAG2AXI bridge
// launches is the one its JTAG request asked for, and a request never
// reaches the bus while the bridge's lifecycle disable is asserted.
// Consumes the reconstructed scan stream (write) and the per-TCK event
// stream (event_export) through a dtp_jtag_ir_model to know the active
// instruction, decodes every DR scan that addresses a bridge register
// through a dtp_jtag2axi_model, feeds that model the completions observed
// on the three bridge ports (axi_export) so its series address and busy
// state follow the DUT, and publishes one expected ocah_axi_item
// (direction, address, size, strobes, data) per launched transaction on
// the lane of the port that will carry it. The scoreboard pairs those in
// order with the observed transactions of the same port. Gating is read
// from dtp_tb_if.dbg_disable at the scan; a TAP reset (TRST, TMS, power-on)
// resets the bridge model, a system reset aborts its in-flight
// transactions. `negative` (+DTP_J2A_REF_MODEL_NEGATIVE) corrupts every
// predicted address so the pairing must fail. No comparison, no reporting.
// The cocotb realization has no twin (DTP_TB_ARCH).

`uvm_analysis_imp_decl(_dtp_j2a_req_event)
`uvm_analysis_imp_decl(_dtp_j2a_req_axi)

class dtp_jtag2axi_req_ref_model extends ocah_ref_model #(ocah_jtag_scan_item, ocah_axi_item);
  `uvm_component_utils(dtp_jtag2axi_req_ref_model)

  virtual dtp_tb_if tb_vif;
  // Negative validation: predict a wrong address on every request.
  bit negative;

  uvm_analysis_imp_dtp_j2a_req_event #(ocah_jtag_event, dtp_jtag2axi_req_ref_model) event_export;
  uvm_analysis_imp_dtp_j2a_req_axi   #(ocah_axi_item, dtp_jtag2axi_req_ref_model)   axi_export;

  protected dtp_jtag_ir_model  m_ir;
  protected dtp_jtag2axi_model m_bridge;
  // Bridge name <-> the monitor publishing its port (the item `source`).
  protected string             m_source[string];
  protected string             m_target_by_source[string];
  protected bit [31:0]         m_sys_rst_seen;

  function new(string name = "dtp_jtag2axi_req_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    event_export = new("event_export", this);
    axi_export   = new("axi_export", this);
    m_ir         = new();
    m_bridge     = new();
  endfunction

  // Name the monitor whose items carry a bridge's transactions
  // (connect_phase of dtp_env).
  function void bind_port(string target, string source);
    m_source[target]           = source;
    m_target_by_source[source] = target;
  endfunction

  // Reconstructed scans: IR scans track the instruction; a DR scan that
  // addresses a bridge register is decoded and applied.
  function void write(ocah_jtag_scan_item t);
    dtp_j2a_target_t  target;
    dtp_j2a_request_t req;
    ocah_axi_item     exp;
    sync_reset();
    if (t.is_ir) begin
      m_ir.on_ir_scan(t);
      return;
    end
    if (!m_ir.ir_known()) return;
    if (m_bridge.decode(m_ir.ir(), t, target, req) == DTP_J2A_SCAN_NONE) return;
    if (dtp_dbg_path_disabled(tb_vif.dbg_disable, target.dbg_path)) begin
      m_bridge.gated(target.name);
      return;
    end
    if (!m_bridge.update(target, req, t.end_time, exp)) return;
    if (!m_source.exists(target.name))
      `uvm_fatal(get_type_name(), $sformatf("bridge `%s` has no bound port", target.name))
    exp.source     = m_source[target.name];
    exp.start_time = t.end_time;
    exp.end_time   = t.end_time;
    if (negative) exp.address = exp.address ^ 64'h4;
    expected_ap.write(exp);
  endfunction

  function void write_dtp_j2a_req_event(ocah_jtag_event t);
    sync_reset();
    void'(m_ir.on_event(t));
    consume_tap_reset();
  endfunction

  function void write_dtp_j2a_req_axi(ocah_axi_item t);
    if (!m_target_by_source.exists(t.source))
      `uvm_fatal(get_type_name(), $sformatf("AXI item from unbound port `%s`", t.source))
    m_bridge.complete(m_target_by_source[t.source], t);
  endfunction

  // Power-on reset resets the TAP and with it every bridge; a system
  // reset aborts the AXI side only.
  protected function void sync_reset();
    void'(m_ir.sync_power_on_reset(tb_vif.por_assert_count));
    consume_tap_reset();
    if (tb_vif.sys_rst_assert_count !== m_sys_rst_seen) begin
      m_sys_rst_seen = tb_vif.sys_rst_assert_count;
      m_bridge.abort_in_flight();
    end
  endfunction

  // The bridges' JTAG-side registers reset whenever the TAP is in
  // Test-Logic-Reset (jtag_tap_ctrlr host_dr_scan_ctrl_o.rst_n).
  protected function void consume_tap_reset();
    if (m_ir.take_tap_reset()) m_bridge.reset();
  endfunction

endclass : dtp_jtag2axi_req_ref_model
