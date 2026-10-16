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
// the lane of the port that will carry it. A scan takes effect on the TCK
// cycle that leaves Update-DR, which a scan held in Pause-DR delays. The
// scoreboard pairs those in order with the observed transactions of the
// same port. Gating is read from dtp_tb_if.dbg_disable at that cycle and at
// each completion, which drops
// the requests queued behind it while the bridge is disabled; a TAP reset
// (TRST, TMS, power-on) resets the bridge model, a system reset aborts its
// in-flight transactions. `negative` (+DTP_J2A_REF_MODEL_NEGATIVE) corrupts every
// predicted address so the pairing must fail. No comparison, no reporting.
// The cocotb twin is env/dtp_jtag2axi_req_ref_model.py.

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
  // The bridge scan waiting for the TAP to leave Update-DR.
  protected bit                m_pending;
  protected dtp_j2a_target_t   m_pending_target;
  protected dtp_j2a_request_t  m_pending_req;

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
  // addresses a bridge register is decoded and waits for its Update-DR.
  function void write(ocah_jtag_scan_item t);
    dtp_j2a_target_t  target;
    dtp_j2a_request_t req;
    sync_reset();
    if (t.is_ir) begin
      m_ir.on_ir_scan(t);
      return;
    end
    if (!m_ir.ir_known()) return;
    if (m_bridge.decode(m_ir.ir(), t, target, req) == DTP_J2A_SCAN_NONE) return;
    m_pending        = 1'b1;
    m_pending_target = target;
    m_pending_req    = req;
  endfunction

  // The pending scan's Update-DR, on the TCK cycle that leaves it.
  protected function void apply_update(dtp_j2a_target_t target, dtp_j2a_request_t req,
                                       time update_time);
    ocah_axi_item exp;
    if (dtp_dbg_path_disabled(tb_vif.dbg_disable, target.dbg_path)) begin
      m_bridge.gated(target.name);
      return;
    end
    if (!m_bridge.update(target, req, update_time, exp) || m_bridge.abort_pending()) return;
    if (!m_source.exists(target.name))
      `uvm_fatal(get_type_name(), $sformatf("bridge `%s` has no bound port", target.name))
    exp.source     = m_source[target.name];
    exp.start_time = update_time;
    exp.end_time   = update_time;
    if (negative) exp.address = exp.address ^ 64'h4;
    expected_ap.write(exp);
  endfunction

  function void write_dtp_j2a_req_event(ocah_jtag_event t);
    sync_reset();
    if (t.kind == OCAH_JTAG_EV_STEP && t.trst_n) m_bridge.tck_step();
    if (m_pending && t.kind == OCAH_JTAG_EV_STEP && t.trst_n &&
        m_ir.tap_state() == OCAH_JTAG_UPDATE_DR) begin
      m_pending = 1'b0;
      apply_update(m_pending_target, m_pending_req, t.timestamp);
    end
    void'(m_ir.on_event(t));
    consume_tap_reset();
  endfunction

  function void write_dtp_j2a_req_axi(ocah_axi_item t);
    dtp_j2a_target_t target;
    if (!m_target_by_source.exists(t.source))
      `uvm_fatal(get_type_name(), $sformatf("AXI item from unbound port `%s`", t.source))
    target = dtp_j2a_target_by_name(m_target_by_source[t.source]);
    m_bridge.complete(target.name, t, dtp_dbg_path_disabled(tb_vif.dbg_disable, target.dbg_path));
  endfunction

  // Power-on reset resets the TAP and with it every bridge; a system
  // reset aborts the AXI side only.
  protected function void sync_reset();
    void'(m_ir.sync_power_on_reset(tb_vif.por_assert_count));
    consume_tap_reset();
    if (tb_vif.sys_rst_assert_count !== m_sys_rst_seen) begin
      m_sys_rst_seen = tb_vif.sys_rst_assert_count;
      m_bridge.system_reset();
    end
  endfunction

  // The bridges' JTAG-side registers reset whenever the TAP is in
  // Test-Logic-Reset (jtag_tap_ctrlr host_dr_scan_ctrl_o.rst_n).
  protected function void consume_tap_reset();
    if (m_ir.take_tap_reset()) begin
      m_pending = 1'b0;
      m_bridge.reset();
    end
  endfunction

endclass : dtp_jtag2axi_req_ref_model
