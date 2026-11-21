// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// jtag2axi_status reference model: a DMI capture presents the address and
// data of the last DMI update, the read response after a read, and the
// sticky DMI status; a DTMCS capture presents the bridge's fixed DTM fields
// and the same status. Consumes the reconstructed scan stream (write), the
// per-TCK event stream (event_export) and the transactions observed on the
// three bridge ports (axi_export) through a dtp_jtag2axi_tracker and
// publishes one dtp_jtag2axi_status_item per scan item, so the scoreboard
// pairs the two streams in lockstep; scans that are not a bridge capture,
// and captures while the PTAP 3DCR select is set, carry no contract.
// `negative` leaves the status at 0 where a capture or update finds a DMI
// operation in progress, so the busy captures that follow must disagree. No
// comparison, no reporting. The cocotb twin is
// env/dtp_jtag2axi_status_ref_model.py.

`uvm_analysis_imp_decl(_dtp_j2a_status_event)
`uvm_analysis_imp_decl(_dtp_j2a_status_axi)

class dtp_jtag2axi_status_ref_model
    extends ocah_ref_model #(ocah_jtag_scan_item, dtp_jtag2axi_status_item);
  `uvm_component_utils(dtp_jtag2axi_status_ref_model)

  virtual dtp_tb_if tb_vif;
  bit               negative;

  uvm_analysis_imp_dtp_j2a_status_event #(ocah_jtag_event, dtp_jtag2axi_status_ref_model)
        event_export;
  uvm_analysis_imp_dtp_j2a_status_axi #(ocah_axi_item, dtp_jtag2axi_status_ref_model)
        axi_export;

  protected dtp_jtag2axi_tracker m_tracker;

  function new(string name = "dtp_jtag2axi_status_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    event_export = new("event_export", this);
    axi_export   = new("axi_export", this);
    m_tracker    = new(tb_vif, negative);
  endfunction

  // Name the monitor whose items carry a bridge's transactions
  // (connect_phase of dtp_env).
  function void bind_port(string target, string source);
    m_tracker.bind_port(target, source);
  endfunction

  function void write(ocah_jtag_scan_item t);
    expected_ap.write(m_tracker.on_scan(t));
  endfunction

  function void write_dtp_j2a_status_event(ocah_jtag_event t);
    string        target;
    ocah_axi_item launched;
    void'(m_tracker.on_event(t, target, launched));
  endfunction

  function void write_dtp_j2a_status_axi(ocah_axi_item t);
    m_tracker.on_axi(t);
  endfunction

endclass : dtp_jtag2axi_status_ref_model
