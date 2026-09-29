// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive monitor of the SMU boundary's reset releases: samples smu_tb_if on
// every SMU clock and publishes one smu_pin_event_item on each 0 -> 1
// transition of smc_fuse_reset_n_delayed_o and of the SMC primary reset,
// with the boot-gate input and the fuse-sense flag sampled in the same
// clock. Observes only; the boot_gate reference model and the scoreboard
// judge the stream. A four-state sample that is not 1 counts as low, so a
// rise out of X is still a rise.

class smu_reset_pin_monitor extends uvm_component;
  `uvm_component_utils(smu_reset_pin_monitor)

  virtual smu_tb_if tb_vif;
  uvm_analysis_port #(smu_pin_event_item) item_ap;

  function new(string name = "smu_reset_pin_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smu_tb_if `tb_vif` not set by the env")
    item_ap = new("item_ap", this);
  endfunction

  task run_phase(uvm_phase phase);
    bit fuse_q    = 1'b0;
    bit primary_q = 1'b0;
    forever begin
      bit fuse_d, primary_d;
      @(posedge tb_vif.clk_smu);
      fuse_d    = (tb_vif.fuse_reset_n_delayed === 1'b1);
      primary_d = (tb_vif.rst_primary_smc_clk_n === 1'b1);
      if (fuse_d && !fuse_q) publish(SMU_PIN_EV_FUSE_RESET_RELEASE);
      if (primary_d && !primary_q) publish(SMU_PIN_EV_PRIMARY_RESET_RELEASE);
      fuse_q    = fuse_d;
      primary_q = primary_d;
    end
  endtask

  protected function void publish(smu_pin_event_kind_e kind);
    smu_pin_event_item item = smu_pin_event_item::type_id::create("pin_event");
    item.kind              = kind;
    item.ext_boot_seq_done = (tb_vif.ext_boot_seq_done === 1'b1);
    item.fuse_sense_done   = (tb_vif.fuse_sense_done === 1'b1);
    item.timestamp         = $time;
    `uvm_info(get_type_name(), item.convert2string(), UVM_MEDIUM)
    item_ap.write(item);
  endfunction

endclass : smu_reset_pin_monitor
