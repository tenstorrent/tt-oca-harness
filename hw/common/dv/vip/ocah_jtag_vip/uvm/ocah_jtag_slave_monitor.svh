// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive JTAG monitor at the slave-side observation point. Watches the
// same IEEE 1149.1 wire as the master-side monitor and emits the identical
// ocah_jtag_event stream (STEP per TCK cycle, published on the falling
// edge; asynchronous TRST edges); it exists as the slave agent's own
// component so device-side agents bind to ocah_jtag_slave_config and label
// their streams distinctly.

class ocah_jtag_slave_monitor extends uvm_monitor;
  `uvm_component_utils(ocah_jtag_slave_monitor)

  ocah_jtag_slave_config cfg;

  uvm_analysis_port #(ocah_jtag_event) event_ap;

  protected int unsigned m_step_index;

  function new(string name = "ocah_jtag_slave_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_slave_config)::get(this, "", "slave_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_slave_config `slave_cfg` not found in uvm_config_db")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "ocah_jtag_slave_config.vif is null")
    event_ap = new("event_ap", this);
  endfunction

  task run_phase(uvm_phase phase);
    fork
      watch_tck();
      watch_trst();
    join
  endtask

  // Same sampling contract as the master-side monitor: tms/tdi/tdo at the
  // rising edge (tdo last changed on the previous falling edge), publish
  // at the falling edge once the rising-edge state transition settled.
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

endclass : ocah_jtag_slave_monitor
