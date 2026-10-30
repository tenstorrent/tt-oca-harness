// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Counts single-beat SEP_IN requests and responses across one reset epoch.
class smc_sep_in_reset_monitor extends uvm_component;
  `uvm_component_utils(smc_sep_in_reset_monitor)
  virtual ocah_axi_if vif;
  virtual smc_tb_if tb_vif;
  bit armed, reset_seen, phase_valid, sva_disabled, write_cell;
  bit master_ready_low;
  logic sampled_bready, sampled_rready;
  int unsigned sample_count, extra_resets;
  bit request_idle, held_response;
  int unsigned aw, w, ar, b, r, write_complete, pending_read;
  int unsigned orphan_b, orphan_r, shape_errors, stale_b, stale_r;
  int unsigned b_valid_with_pending, r_valid_with_pending, held_valid, abandoned;
  string phase_context;

  function new(string name = "smc_sep_in_reset_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function int unsigned pending_write();
    int unsigned accepted = aw < w ? aw : w;
    return accepted > write_complete ? accepted - write_complete : 0;
  endfunction

  function void clear_counts();
    aw = 0;
    w = 0;
    ar = 0;
    b = 0;
    r = 0;
    write_complete = 0;
    pending_read = 0;
    held_valid = 0;
  endfunction

  function void arm(bit is_write);
    if (armed || vif == null || vif.aresetn !== 1'b1) begin
      `uvm_fatal(get_type_name(), "Reset monitor must be idle and out of reset before arm")
    end
    write_cell = is_write;
    reset_seen = 0;
    phase_valid = 0;
    phase_context = "";
    abandoned = 0;
    extra_resets = 0;
    sva_disabled = 0;
    stale_b = 0;
    stale_r = 0;
    orphan_b = 0;
    orphan_r = 0;
    shape_errors = 0;
    b_valid_with_pending = 0;
    r_valid_with_pending = 0;
    request_idle = 0;
    held_response = 0;
    master_ready_low = 0;
    clear_counts();
    armed = 1;
  endfunction

  function void disarm();
    armed = 0;
  endfunction

  protected function void reset_epoch();
    int unsigned held_before = held_valid;
    phase_context = $sformatf(
        "request_idle=%0b held_response=%0b aw=%0d w=%0d ar=%0d b=%0d r=%0d held_valid=%0d",
        request_idle, held_response, aw, w, ar, b, r, held_valid);
    phase_valid = request_idle && held_response && b == 0 && r == 0 &&
        (write_cell ? aw == 2 && w == 2 && ar == 0 : ar == 2 && aw == 0 && w == 0);
    abandoned = pending_write() + pending_read;
    clear_counts();
    held_valid = held_before;
    reset_seen = 1;
  endfunction

  function string counters_context();
    return $sformatf(
        {
          "aw=%0d w=%0d ar=%0d b=%0d r=%0d pending_write=%0d pending_read=%0d ",
          "b_valid_with_pending=%0d r_valid_with_pending=%0d ",
          "stale_b=%0d stale_r=%0d orphan_b=%0d orphan_r=%0d shape_errors=%0d extra_resets=%0d"
        },
        aw,
        w,
        ar,
        b,
        r,
        pending_write(),
        pending_read,
        b_valid_with_pending,
        r_valid_with_pending,
        stale_b,
        stale_r,
        orphan_b,
        orphan_r,
        shape_errors,
        extra_resets
    );
  endfunction

  protected task sample_path();
    forever begin
      @(vif.mon_cb);
      sample_count++;
      request_idle = vif.mon_cb.awvalid === 1'b0 && vif.mon_cb.wvalid === 1'b0 &&
          vif.mon_cb.arvalid === 1'b0;
      sampled_bready = vif.mon_cb.bready;
      sampled_rready = vif.mon_cb.rready;
      master_ready_low = sampled_bready === 1'b0 && sampled_rready === 1'b0;
      held_response = write_cell ?
          vif.mon_cb.bvalid === 1'b1 && sampled_bready === 1'b0 :
          vif.mon_cb.rvalid === 1'b1 && sampled_rready === 1'b0;
      if (!armed) continue;
      if (tb_vif.axi_sva_en !== 1'b1) sva_disabled = 1;
      if (vif.aresetn !== 1'b1) continue;
      if (!reset_seen && held_response) held_valid++;
      if (reset_seen && vif.mon_cb.bvalid === 1'b1) begin
        if (pending_write() == 0) stale_b++;
        else b_valid_with_pending++;
      end
      if (reset_seen && vif.mon_cb.rvalid === 1'b1) begin
        if (pending_read == 0) stale_r++;
        else r_valid_with_pending++;
      end
      // Responses use only requests accepted before this sample.
      if (vif.mon_cb.bvalid === 1'b1 && vif.mon_cb.bready === 1'b1) begin
        b++;
        if (pending_write() == 0) orphan_b++;
        else write_complete++;
      end
      if (vif.mon_cb.rvalid === 1'b1 && vif.mon_cb.rready === 1'b1) begin
        r++;
        if (pending_read == 0) orphan_r++;
        else pending_read--;
        if (vif.mon_cb.rlast !== 1'b1) shape_errors++;
      end
      if (vif.mon_cb.awvalid === 1'b1 && vif.mon_cb.awready === 1'b1) begin
        aw++;
        if (vif.mon_cb.awlen !== 0) shape_errors++;
      end
      if (vif.mon_cb.wvalid === 1'b1 && vif.mon_cb.wready === 1'b1) begin
        w++;
        if (vif.mon_cb.wlast !== 1'b1) shape_errors++;
      end
      if (vif.mon_cb.arvalid === 1'b1 && vif.mon_cb.arready === 1'b1) begin
        ar++;
        pending_read++;
        if (vif.mon_cb.arlen !== 0) shape_errors++;
      end
    end
  endtask

  task run_phase(uvm_phase phase);
    if (vif == null || tb_vif == null) begin
      `uvm_fatal(get_type_name(), "Reset monitor interfaces are not connected")
    end
    fork
      sample_path();
      forever begin
        @(negedge vif.aresetn);
        if (!armed) continue;
        if (!reset_seen) reset_epoch();
        else begin
          extra_resets++;
          clear_counts();
        end
      end
    join
  endtask
endclass : smc_sep_in_reset_monitor
