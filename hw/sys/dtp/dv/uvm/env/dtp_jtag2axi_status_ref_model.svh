// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// jtag2axi_status reference model: the status a SINGLE_OP or SERIES_CTRL
// scan captures is the outcome of the bridge's completed AXI transactions
// (SUCCESS, SLVERR, DECERR, or BUSY_OR_FULL while one is pending), and the
// data a SINGLE_OP capture returns after a completed OKAY read is the word
// the bus returned. Consumes the reconstructed scan stream (write) and the
// per-TCK event stream (event_export) through a dtp_jtag_ir_model, applies
// every bridge-register DR scan and every observed bridge completion
// (axi_export) to a dtp_jtag2axi_model, and publishes one
// dtp_jtag2axi_status_item per scan item so the scoreboard pairs the two
// streams in lockstep; scans that are not a bridge capture, and captures
// inside the CDC settle window after a completion, carry no contract.
// Series-data captures (the pipelined read FIFO) are not predicted. No
// comparison, no reporting. The cocotb realization has no twin
// (DTP_TB_ARCH).

`uvm_analysis_imp_decl(_dtp_j2a_status_event)
`uvm_analysis_imp_decl(_dtp_j2a_status_axi)

class dtp_jtag2axi_status_ref_model
    extends ocah_ref_model #(ocah_jtag_scan_item, dtp_jtag2axi_status_item);
  `uvm_component_utils(dtp_jtag2axi_status_ref_model)

  dtp_env_cfg       cfg;
  virtual dtp_tb_if tb_vif;

  uvm_analysis_imp_dtp_j2a_status_event #(ocah_jtag_event, dtp_jtag2axi_status_ref_model)
        event_export;
  uvm_analysis_imp_dtp_j2a_status_axi #(ocah_axi_item, dtp_jtag2axi_status_ref_model)
        axi_export;

  protected dtp_jtag_ir_model  m_ir;
  protected dtp_jtag2axi_model m_bridge;
  protected string             m_target_by_source[string];
  protected bit [31:0]         m_sys_rst_seen;

  function new(string name = "dtp_jtag2axi_status_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(dtp_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "dtp_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    event_export = new("event_export", this);
    axi_export   = new("axi_export", this);
    m_ir         = new();
    m_bridge     = new();
    // CDC window after a completion during which a capture is not checkable.
    m_bridge.settle_window = DtpJ2aStatusSettleTck * 2 * cfg.tck_half_period_ns * 1ns;
  endfunction

  // Name the monitor whose items carry a bridge's transactions
  // (connect_phase of dtp_env).
  function void bind_port(string target, string source);
    m_target_by_source[source] = target;
  endfunction

  // One expected capture per scan item: predicted at the scan's
  // Capture-DR, then the scan's Update-DR is applied to the model.
  function void write(ocah_jtag_scan_item t);
    dtp_j2a_target_t         target;
    dtp_j2a_request_t        req;
    dtp_j2a_scan_kind_e      kind;
    ocah_axi_item            unused;
    dtp_jtag2axi_status_item exp =
            dtp_jtag2axi_status_item::type_id::create("exp");
    exp.timestamp = t.end_time;
    exp.compare   = 1'b0;
    sync_reset();
    if (t.is_ir) begin
      m_ir.on_ir_scan(t);
      expected_ap.write(exp);
      return;
    end
    kind = m_ir.ir_known() ? m_bridge.decode(m_ir.ir(), t, target, req) : DTP_J2A_SCAN_NONE;
    if (kind != DTP_J2A_SCAN_NONE) begin
      if ((kind == DTP_J2A_SCAN_SINGLE_OP) || (kind == DTP_J2A_SCAN_SERIES_CTRL)) begin
        m_bridge.predict_capture(target, kind, t.start_time, exp);
        exp.context_s = $sformatf("%s %s bits=%0d", target.name, kind.name(), t.bit_count);
      end
      if (dtp_dbg_path_disabled(tb_vif.dbg_disable, target.dbg_path)) m_bridge.gated(target.name);
      else void'(m_bridge.update(target, req, t.end_time, unused));
    end
    expected_ap.write(exp);
  endfunction

  function void write_dtp_j2a_status_event(ocah_jtag_event t);
    sync_reset();
    void'(m_ir.on_event(t));
    consume_tap_reset();
  endfunction

  function void write_dtp_j2a_status_axi(ocah_axi_item t);
    if (!m_target_by_source.exists(t.source))
      `uvm_fatal(get_type_name(), $sformatf("AXI item from unbound port `%s`", t.source))
    m_bridge.complete(m_target_by_source[t.source], t);
  endfunction

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

endclass : dtp_jtag2axi_status_ref_model
