// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// boot_gate reference model: the SMC fuse reset is released only once the
// external boot-sequence gate is open and the SMC eFuse sense has completed
// (doc/integrator/src/smu.adoc port table: ext_boot_seq_done_i gates the
// reset release; the SMC reset unit releases fuse_reset after sense done).
// Subscribes to the reset-release stream of smu_reset_pin_monitor and, for
// every fuse-reset release, publishes the gate and sense levels that release
// requires; a primary-reset release carries no contract, since that reset is
// not gated by the pin (the negative control of the boot-gate scenario).
// cfg.boot_gate_negative (+SMU_BOOT_GATE_SCOREBOARD_NEGATIVE) predicts a
// closed gate instead, so the scoreboard must fail on the first release. No
// comparison and no verdict live here. No cocotb twin.

class smu_boot_gate_ref_model extends ocah_ref_model #(smu_pin_event_item, smu_pin_event_item);
  `uvm_component_utils(smu_boot_gate_ref_model)

  smu_env_cfg cfg;

  function new(string name = "smu_boot_gate_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smu_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smu_env_cfg `env_cfg` not found in uvm_config_db")
    if (cfg.boot_gate_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: fuse-reset release predicted with the boot gate closed",
                UVM_LOW)
  endfunction

  function void write(smu_pin_event_item t);
    smu_pin_event_item e = smu_pin_event_item::type_id::create("expected");
    e.kind      = t.kind;
    e.timestamp = t.timestamp;
    e.compare   = (t.kind == SMU_PIN_EV_FUSE_RESET_RELEASE);
    if (e.compare) begin
      m_releases++;
      e.ext_boot_seq_done = cfg.boot_gate_negative ? 1'b0 : 1'b1;
      e.fuse_sense_done   = 1'b1;
      e.context_s         = $sformatf("fuse-reset release #%0d", m_releases);
    end
    expected_ap.write(e);
  endfunction

  protected int unsigned m_releases;

endclass : smu_boot_gate_ref_model
