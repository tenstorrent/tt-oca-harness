// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Slave-side agent bundle: the reactive memory-backed responder.
//
// Reactive agent: there is NO sequencer — the driver answers bus traffic on
// its own, and tests configure/inspect it through ocah_axi_slave_sequence
// (exposed here pre-bound as `seq`). Bus observation stays with the
// side-neutral passive ocah_axi_env; this agent does not duplicate a monitor.

class ocah_axi_slave_agent extends uvm_agent;
  `uvm_component_utils(ocah_axi_slave_agent)

  ocah_axi_slave_config   cfg;
  ocah_axi_slave_driver   m_driver;
  ocah_axi_slave_sequence seq;

  function new(string name = "ocah_axi_slave_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (cfg == null && !uvm_config_db#(ocah_axi_slave_config)::get(this, "", "slave_cfg", cfg))
      `uvm_fatal(get_type_name(), "ocah_axi_slave_config `slave_cfg` not found")
    if (cfg.is_active == UVM_ACTIVE) begin
      uvm_config_db#(ocah_axi_slave_config)::set(this, "m_driver", "slave_cfg", cfg);
      m_driver = ocah_axi_slave_driver::type_id::create("m_driver", this);
      seq = ocah_axi_slave_sequence::type_id::create({get_name(), "_seq"});
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (seq != null) seq.responder = m_driver;
  endfunction

endclass : ocah_axi_slave_agent
