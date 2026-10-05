// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Slave-side (reactive TAP device) agent: monitor always (when en_monitor);
// the reactive device driver when cfg.is_active == UVM_ACTIVE. Reactive: the
// external host supplies all stimulus, so there is no sequencer; tests
// configure and inspect the device through ocah_jtag_slave_sequence bound to
// m_driver.

class ocah_jtag_slave_agent extends uvm_agent;
  `uvm_component_utils(ocah_jtag_slave_agent)

  ocah_jtag_slave_config  cfg;
  ocah_jtag_slave_driver  m_driver;
  ocah_jtag_slave_monitor m_monitor;

  function new(string name = "ocah_jtag_slave_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_slave_config)::get(this, "", "slave_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_slave_config `slave_cfg` not found in uvm_config_db")
    if (cfg.en_monitor) m_monitor = ocah_jtag_slave_monitor::type_id::create("m_monitor", this);
    if (cfg.is_active == UVM_ACTIVE)
      m_driver = ocah_jtag_slave_driver::type_id::create("m_driver", this);
  endfunction

endclass : ocah_jtag_slave_agent
