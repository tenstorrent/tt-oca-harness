// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VIP-level environment encapsulating the JTAG agent — the unit DUT
// environments instantiate, and the unit a commercial-VIP integration
// overrides (matching the delivery granularity of commercial VIPs, which
// ship system envs, not bare agents).
//
// Frozen surface (all a DUT env / sequence may depend on):
//   * m_sequencer — scenario handle; sequences issue ocah_jtag_item here
//   * event_ap    — ocah_jtag_event observation stream (pass-through from
//                   the OCAH passive monitor; silent when cfg.en_monitor=0)
//   * cfg         — ocah_jtag_master_config (+ opaque cfg.vendor_cfg for subclasses)
//
// Commercial-VIP integration (user-implemented; see README "Template
// Contract"): inherit this env (and the agent if needed), build the vendor
// system env instead, implement the API-wrapper translation (ocah_jtag_item
// -> vendor transactions started on the vendor sequencer), set
// cfg.en_monitor = 0 (the vendor env owns driving AND monitoring), and
// publish the vendor interface nested inside ocah_jtag_if via
// uvm_config_db::set. Then select the subclass with one factory override:
//   ocah_jtag_master_env::type_id::set_type_override(<vendor>_jtag_env::get_type())

class ocah_jtag_master_env extends uvm_env;
  `uvm_component_utils(ocah_jtag_master_env)

  ocah_jtag_master_config       cfg;
  ocah_jtag_master_agent     m_agent;

  // Optional functional-coverage subscriber (cfg.en_cov; commercial-sim
  // flows only). Its scan_export stays available for a DUT env that owns a
  // scan builder.
  ocah_jtag_cov       m_cov;

  // Frozen surface.
  ocah_jtag_master_sequencer m_sequencer;
  uvm_analysis_port #(ocah_jtag_event) event_ap;

  function new(string name = "ocah_jtag_master_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (cfg == null && !uvm_config_db#(ocah_jtag_master_config)::get(this, "", "cfg", cfg))
      `uvm_fatal(get_type_name(), "ocah_jtag_master_config `cfg` not found in uvm_config_db")
    event_ap = new("event_ap", this);
    uvm_config_db#(ocah_jtag_master_config)::set(this, "m_agent*", "cfg", cfg);
    m_agent = ocah_jtag_master_agent::type_id::create("m_agent", this);
    if (cfg.en_cov) begin
      if (!cfg.en_monitor)
        `uvm_fatal(get_type_name(),
                   "cfg.en_cov requires cfg.en_monitor (coverage samples the event stream)")
      uvm_config_db#(ocah_jtag_master_config)::set(this, "m_cov*", "cfg", cfg);
      m_cov = ocah_jtag_cov::type_id::create("m_cov", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (cfg.is_active == UVM_ACTIVE) m_sequencer = m_agent.m_sequencer;
    if (cfg.en_monitor) m_agent.m_monitor.event_ap.connect(event_ap);
    if (m_cov != null) m_agent.m_monitor.event_ap.connect(m_cov.analysis_export);
  endfunction

endclass : ocah_jtag_master_env
