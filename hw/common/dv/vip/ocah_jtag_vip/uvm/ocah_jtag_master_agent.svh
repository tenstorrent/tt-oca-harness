// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Standard JTAG agent: monitor always; driver + sequencer when
// cfg.is_active == UVM_ACTIVE. The environment publishes the cfg with
// uvm_config_db#(ocah_jtag_master_config)::set(this, "<agent>*", "cfg", cfg) so the
// agent's children resolve the same object.

class ocah_jtag_master_agent extends uvm_agent;
  `uvm_component_utils(ocah_jtag_master_agent)

  ocah_jtag_master_config       cfg;
  ocah_jtag_master_driver    m_driver;
  ocah_jtag_master_sequencer m_sequencer;
  ocah_jtag_master_monitor   m_monitor;

  function new(string name = "ocah_jtag_master_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_master_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_master_config `cfg` not found in uvm_config_db")
    // en_monitor=0 is the commercial-VIP posture: the vendor env owns
    // driving AND monitoring, so no OCAH monitor is constructed.
    if (cfg.en_monitor) m_monitor = ocah_jtag_master_monitor::type_id::create("m_monitor", this);
    if (cfg.is_active == UVM_ACTIVE) begin
      m_driver    = ocah_jtag_master_driver::type_id::create("m_driver", this);
      m_sequencer = ocah_jtag_master_sequencer::type_id::create("m_sequencer", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) m_driver.seq_item_port.connect(m_sequencer.seq_item_export);
  endfunction

endclass : ocah_jtag_master_agent
