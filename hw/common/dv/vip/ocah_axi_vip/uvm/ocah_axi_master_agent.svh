// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Master-side agent bundle: driver + sequencer when cfg.is_active ==
// UVM_ACTIVE. The environment publishes the cfg with
// uvm_config_db#(ocah_axi_master_config)::set(this, "<agent>*", "cfg", cfg)
// so the agent's children resolve the same object.
//
// No agent-attached monitor: bus observation stays with the side-neutral
// passive ocah_axi_env (the wire does not know which side generated the
// traffic), so this agent does not duplicate one. Point the passive env at
// the same ocah_axi_if to observe/score the traffic this agent drives.

class ocah_axi_master_agent extends uvm_agent;
  `uvm_component_utils(ocah_axi_master_agent)

  ocah_axi_master_config    cfg;
  ocah_axi_master_driver    m_driver;
  ocah_axi_master_sequencer m_sequencer;

  function new(string name = "ocah_axi_master_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (cfg == null && !uvm_config_db#(ocah_axi_master_config)::get(this, "", "cfg", cfg))
      `uvm_fatal(get_type_name(), "ocah_axi_master_config `cfg` not found in uvm_config_db")
    if (cfg.is_active == UVM_ACTIVE) begin
      m_driver    = ocah_axi_master_driver::type_id::create("m_driver", this);
      m_sequencer = ocah_axi_master_sequencer::type_id::create("m_sequencer", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) m_driver.seq_item_port.connect(m_sequencer.seq_item_export);
  endfunction

endclass : ocah_axi_master_agent
