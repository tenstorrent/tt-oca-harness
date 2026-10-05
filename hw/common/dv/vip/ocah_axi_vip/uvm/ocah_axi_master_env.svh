// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VIP-level environment encapsulating the AXI master agent — the unit DUT
// environments instantiate, and the unit a commercial-VIP integration
// overrides (matching the delivery granularity of commercial VIPs, which
// ship system envs, not bare agents; same template contract as
// ocah_jtag_master_env).
//
// Frozen surface (all a DUT env / sequence may depend on):
//   * m_sequencer — scenario handle; sequences issue ocah_axi_item here
//                   (drive it through ocah_axi_master_sequence, never raw)
//   * cfg         — ocah_axi_master_config (+ opaque cfg.vendor_cfg for
//                   subclasses)
//
// Bus observation is NOT part of this surface: the side-neutral passive
// ocah_axi_env owns the monitor/model/scoreboard stack — instantiate it on
// the same ocah_axi_if to observe the traffic this env drives.
//
// Commercial-VIP integration (user-implemented; see README "Template
// Contract" in the JTAG VIP): inherit this env, build the vendor system env
// instead, implement the API-wrapper translation (ocah_axi_item -> vendor
// transactions started on the vendor sequencer), and publish the vendor
// interface nested inside ocah_axi_if via uvm_config_db::set. Then select
// the subclass with one factory override:
//   ocah_axi_master_env::type_id::set_type_override(<vendor>_axi_env::get_type())

class ocah_axi_master_env extends uvm_env;
  `uvm_component_utils(ocah_axi_master_env)

  ocah_axi_master_config cfg;
  ocah_axi_master_agent  m_agent;

  // Frozen surface.
  ocah_axi_master_sequencer m_sequencer;

  function new(string name = "ocah_axi_master_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (cfg == null && !uvm_config_db#(ocah_axi_master_config)::get(this, "", "cfg", cfg))
      `uvm_fatal(get_type_name(), "ocah_axi_master_config `cfg` not found in uvm_config_db")
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_agent*", "cfg", cfg);
    m_agent = ocah_axi_master_agent::type_id::create("m_agent", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) m_sequencer = m_agent.m_sequencer;
  endfunction

endclass : ocah_axi_master_env
