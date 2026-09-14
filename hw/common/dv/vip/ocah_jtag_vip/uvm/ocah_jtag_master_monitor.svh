// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive JTAG monitor.
//
// Boundary: samples ONLY the declared ocah_jtag_if pins (tck/tms/trst_n/
// tdi/tdo). It never drives, never consumes sequence intent, and never
// touches DUT-internal or DUT-specific observables — pairing steps with a
// DUT's decoded TAP state is a subscriber's job (e.g. DTP's
// dtp_tap_fsm_checker samples its own DUT-local interface on each event).
//
// Event stream (one flexible object, kind enum):
//   STEP — sampled tms/tdi on the TCK rising edge and TDO stable just
//     before it; PUBLISHED on the following falling edge so subscribers can
//     safely sample DUT observables that update on the rising edge.
//   TRST — asynchronous TRST edges, so subscribers can flush/re-baseline
//     reconstruction state across reset boundaries.
//
// IR/DR scan-level reconstruction (accumulating Shift-x bits across
// Pause/Exit2 re-entries into scan transactions) is ocah_jtag_scan_builder's
// job, layered on this event stream.

class ocah_jtag_master_monitor extends uvm_monitor;
  `uvm_component_utils(ocah_jtag_master_monitor)

  ocah_jtag_master_config cfg;

  uvm_analysis_port #(ocah_jtag_event) event_ap;

  protected int unsigned m_step_index;

  function new(string name = "ocah_jtag_master_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_master_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_master_config `cfg` not found in uvm_config_db")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "ocah_jtag_master_config.vif is null")
    event_ap = new("event_ap", this);
  endfunction

  task run_phase(uvm_phase phase);
    fork
      watch_tck();
      watch_trst();
    join
  endtask

  // One STEP event per TCK cycle. Sample tms/tdi/tdo at the rising edge
  // (tdo last changed on the previous falling edge, so it is race-free
  // there); publish at the falling edge, when the rising-edge state
  // transition has settled for subscribers.
  protected virtual task watch_tck();
    forever begin
      ocah_jtag_event ev;
      @(posedge cfg.vif.tck);
      ev = ocah_jtag_event::type_id::create("ev");
      ev.kind      = OCAH_JTAG_EV_STEP;
      ev.tms       = cfg.vif.tms;
      ev.tdi       = cfg.vif.tdi;
      ev.tdo       = cfg.vif.tdo;
      ev.trst_n    = cfg.vif.trst_n;
      ev.index     = m_step_index++;
      @(negedge cfg.vif.tck);
      ev.timestamp = $time;
      `uvm_info(get_type_name(), ev.convert2string(), UVM_HIGH)
      event_ap.write(ev);
    end
  endtask

  // Asynchronous TRST edges, independent of TCK activity.
  protected virtual task watch_trst();
    forever begin
      ocah_jtag_event ev;
      @(cfg.vif.trst_n);
      ev = ocah_jtag_event::type_id::create("ev");
      ev.kind          = OCAH_JTAG_EV_TRST;
      ev.trst_asserted = (cfg.vif.trst_n === 1'b0);
      ev.trst_n        = cfg.vif.trst_n;
      ev.timestamp     = $time;
      `uvm_info(get_type_name(), ev.convert2string(), UVM_MEDIUM)
      event_ap.write(ev);
    end
  endtask

endclass : ocah_jtag_master_monitor
