// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// jtag2axi_req reference model: every AXI transaction a JTAG2AXI bridge
// launches is the system bus access its Debug Module registers describe when
// the triggering DMI operation reaches it, and no access reaches the port
// while the bridge's lifecycle disable is asserted. Consumes the
// reconstructed scan stream (write), the per-TCK event stream (event_export)
// and the transactions observed on the three bridge ports (axi_export)
// through a dtp_jtag2axi_tracker, and publishes one expected ocah_axi_item
// (direction, address, size, strobes, data) per launched access on the lane
// of the port that will carry it; an access that may take either path is
// published once its port completes it in time. The scoreboard pairs those
// in order with the observed transactions of the same port. `negative`
// (+DTP_J2A_REF_MODEL_NEGATIVE) corrupts every predicted address so the
// pairing must fail. No comparison, no reporting. The cocotb twin is
// env/dtp_jtag2axi_req_ref_model.py.

`uvm_analysis_imp_decl(_dtp_j2a_req_event)
`uvm_analysis_imp_decl(_dtp_j2a_req_axi)

class dtp_jtag2axi_req_ref_model extends ocah_ref_model #(ocah_jtag_scan_item, ocah_axi_item);
  `uvm_component_utils(dtp_jtag2axi_req_ref_model)

  virtual dtp_tb_if tb_vif;
  // Negative validation: predict a wrong address on every request.
  bit negative;

  uvm_analysis_imp_dtp_j2a_req_event #(ocah_jtag_event, dtp_jtag2axi_req_ref_model) event_export;
  uvm_analysis_imp_dtp_j2a_req_axi   #(ocah_axi_item, dtp_jtag2axi_req_ref_model)   axi_export;

  protected dtp_jtag2axi_tracker m_tracker;
  // Bridge name -> the monitor publishing its port (the item `source`).
  protected string               m_source[string];

  function new(string name = "dtp_jtag2axi_req_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    event_export = new("event_export", this);
    axi_export   = new("axi_export", this);
    m_tracker    = new(tb_vif);
  endfunction

  // Name the monitor whose items carry a bridge's transactions
  // (connect_phase of dtp_env).
  function void bind_port(string target, string source);
    m_source[target] = source;
    m_tracker.bind_port(target, source);
  endfunction

  function void write(ocah_jtag_scan_item t);
    void'(m_tracker.on_scan(t));
  endfunction

  function void write_dtp_j2a_req_event(ocah_jtag_event t);
    string        target;
    ocah_axi_item exp;
    if (m_tracker.on_event(t, target, exp)) publish(target, exp, t.timestamp);
  endfunction

  function void write_dtp_j2a_req_axi(ocah_axi_item t);
    string        target;
    ocah_axi_item exp;
    if (m_tracker.on_axi(t, target, exp)) publish(target, exp, t.start_time);
  endfunction

  // Publish a predicted bridge transaction on its port's lane.
  protected function void publish(string target, ocah_axi_item exp, time when);
    if (!m_source.exists(target))
      `uvm_fatal(get_type_name(), $sformatf("bridge `%s` has no bound port", target))
    exp.source     = m_source[target];
    exp.start_time = when;
    exp.end_time   = when;
    if (negative) exp.address ^= 64'h4;
    expected_ap.write(exp);
  endfunction

endclass : dtp_jtag2axi_req_ref_model
